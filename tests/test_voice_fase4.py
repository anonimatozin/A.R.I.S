"""Testes do TTS híbrido (Fase 4): disjuntor + fallback offline.

O log real mostrava ``edge-tts falhou (WSServerHandshakeError: 403)``
repetido a cada fala. A versão do pacote (7.2.8) e o relógio do sistema
estão OK — é rejeição server-side do edge-tts. Logo, a correção é:
- fallback offline (piper → espeak-ng → pyttsx3)
- disjuntor: após N falhas seguidas, pausa o edge e loga UMA vez só.
"""

import time

import pytest

from utils.voice_hybrid import HybridVoice, _env_int


def _bare_voice(**overrides) -> HybridVoice:
    """HybridVoice sem mic seletor nem TTS real (só p/ testar o disjuntor)."""
    v = HybridVoice.__new__(HybridVoice)
    v._logger = None
    v._enabled = True
    v._tts_engine = "edge-tts"
    v._stop_requested = False
    import threading

    v._lock = threading.Lock()
    v._edge_failures = 0
    v._edge_cooldown_until = 0.0
    v._edge_cooldown_logged = False
    v._edge_max_failures = overrides.get("max_failures", 3)
    v._edge_cooldown_s = overrides.get("cooldown_s", 600)
    return v


class TestEnvInt:
    def test_valid(self):
        assert _env_int("X", 5) == 5

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("ARIS_BAD", "abc")
        assert _env_int("ARIS_BAD", 7) == 7


class TestCircuitBreaker:
    def test_edge_success_resets_counter(self, monkeypatch):
        v = _bare_voice()
        v._edge_failures = 2
        monkeypatch.setattr(v, "_edge_tts_speak", lambda t: None)
        monkeypatch.setattr(v, "_speak_offline", lambda t: pytest.fail("não deve cair no offline"))
        # um loop.run_until_complete em cima de None dá erro; entao usamos
        # uma coroutine fake que completa.

        async def ok(text):
            return None

        monkeypatch.setattr(v, "_edge_tts_speak", ok)
        v._speak_edge("olá")
        assert v._edge_failures == 0
        assert v._edge_cooldown_until == 0.0

    def test_failures_open_breaker_and_log_once(self, monkeypatch):
        v = _bare_voice(max_failures=3, cooldown_s=600)
        offline = []
        monkeypatch.setattr(v, "_speak_offline", lambda t: offline.append(t))

        def boom(text):
            raise RuntimeError("403 Forbidden")

        monkeypatch.setattr(v, "_edge_tts_speak", boom)

        logs = []
        monkeypatch.setattr(v, "_log", lambda lvl, msg: logs.append((lvl, msg)))

        for _ in range(5):
            v._speak_edge("olá")

        # Fallback offline chamado em todas as falhas.
        assert len(offline) == 5
        # Disjuntor aberto.
        assert time.monotonic() < v._edge_cooldown_until
        # Disjuntor logado UMA vez só (não spamma 403).
        breaker_logs = [m for lvl, m in logs if "Disjuntor" in m]
        assert len(breaker_logs) == 1

    def test_breaker_open_skips_edge(self, monkeypatch):
        v = _bare_voice()
        # Simula disjuntor já aberto.
        v._edge_cooldown_until = time.monotonic() + 300
        called = []

        def edge_should_not_run(text):
            called.append(text)

        monkeypatch.setattr(v, "_edge_tts_speak", edge_should_not_run)
        monkeypatch.setattr(v, "_speak_offline", lambda t: None)
        v._speak_edge("olá")
        # edge não foi tentado (disjuntor aberto).
        assert called == []


class TestOfflineFallbackOrder:
    def test_offline_tries_piper_then_espeak_then_pyttsx3(self, monkeypatch):
        v = _bare_voice()
        order = []
        monkeypatch.setattr(v, "_speak_piper", lambda t: order.append("piper") or False)
        monkeypatch.setattr(v, "_speak_espeak", lambda t: order.append("espeak") or False)
        monkeypatch.setattr(
            type(v), "_speak_pyttsx3_ptbr",
            staticmethod(lambda text, logger=None: order.append("pyttsx3")),
        )
        v._speak_offline("olá")
        assert order == ["piper", "espeak", "pyttsx3"]

    def test_offline_stops_at_first_success(self, monkeypatch):
        v = _bare_voice()
        order = []
        monkeypatch.setattr(v, "_speak_piper", lambda t: order.append("piper") or True)
        monkeypatch.setattr(v, "_speak_espeak", lambda t: order.append("espeak") or False)
        v._speak_offline("olá")
        assert order == ["piper"]


class TestEspeakAvailable:
    def test_espeak_binary_present_on_this_host(self):
        import shutil

        # Neste Linux o espeak-ng existe; garante que o fallback é real.
        assert shutil.which("espeak-ng") or shutil.which("espeak")
