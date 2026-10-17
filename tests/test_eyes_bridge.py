"""Testes da ponte A.R.I.S. → ARIS Eyes (integração do núcleo).

Cobre o contrato da ponte (utils/eyes_bridge.py):
- mapeamento de TODOS os SystemState para os moods do aris_eyes;
- deduplicação (estado repetido não reenvia);
- falha honesta: olhos parados = False + cache desfeito (re-tenta);
- speech on/off ao entrar/sair de "speaking";
- kill-switch (ARIS_EYES=0), autolaunch opcional;
- personalidade (humor/warmth) enviesando o mood ocioso;
- presença dos hooks no core/aris.py.
"""

import pytest

from modules.esp32_hardware import SystemState
from utils import eyes_bridge

# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_bridge(monkeypatch):
    """Estado zerado + env determinística entre testes."""
    for key in ("ARIS_EYES", "ARIS_EYES_AUTOLAUNCH", "ARIS_EYES_SPEECH_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    # Mood ocioso fixo por padrão; testes de personalidade removem isso.
    monkeypatch.setenv("ARIS_EYES_IDLE_MOOD", "neutral")
    eyes_bridge.reset_for_tests()
    yield
    eyes_bridge.reset_for_tests()


@pytest.fixture
def send_calls(monkeypatch):
    """Grava os comandos que iriam pro socket dos olhos."""
    calls: list[str] = []
    replies: dict[str, str] = {}

    def _fake_send(command, timeout=0.25, path=None):
        calls.append(command)
        return replies.get(command, "ok")

    monkeypatch.setattr(eyes_bridge, "_client_send", _fake_send)
    return {"calls": calls, "replies": replies}


# ── 1. Mapeamento de estados ────────────────────────────────

class TestStateMapping:
    @pytest.mark.parametrize("state,mood", [
        (SystemState.INITIALIZING, "neutral"),
        (SystemState.LISTENING, "listening"),
        (SystemState.THINKING, "thinking"),
        (SystemState.EXECUTING, "thinking"),
        (SystemState.SPEAKING, "speaking"),
        (SystemState.SUCCESS, "happy"),
        (SystemState.ERROR, "error"),
        (SystemState.WARNING, "alert"),
        (SystemState.OFFLINE, "sleeping"),
        (SystemState.IDLE, "neutral"),   # ARIS_EYES_IDLE_MOOD=neutral no fixture
    ])
    def test_every_system_state_maps(self, send_calls, state, mood):
        assert eyes_bridge.set_state(state.value) is True
        expected = [f"state {mood}"]
        if mood == "speaking":
            expected.append("speech 0.60")   # nível de fala junto com o mood
        assert send_calls["calls"] == expected

    def test_esp32_disconnected_ignored(self, send_calls):
        # É estado do LED, não da ARIS: não mexe nos olhos.
        assert eyes_bridge.set_state("esp32_disconnected") is False
        assert send_calls["calls"] == []

    def test_unknown_state_ignored(self, send_calls):
        assert eyes_bridge.set_state("banana") is False
        assert send_calls["calls"] == []


# ── 2. Dedupe e fluxo de comandos ───────────────────────────

class TestDedupeAndFlow:
    def test_same_state_not_sent_twice(self, send_calls):
        assert eyes_bridge.set_state("thinking") is True
        assert eyes_bridge.set_state("thinking") is False
        assert send_calls["calls"] == ["state thinking"]

    def test_transitions_send_each_change(self, send_calls):
        eyes_bridge.set_state("thinking")
        eyes_bridge.set_state("listening")
        eyes_bridge.set_state("idle")
        assert send_calls["calls"] == [
            "state thinking", "state listening", "state neutral",
        ]

    def test_same_mood_different_state_skips(self, send_calls):
        # executing e thinking => mesmo mood "thinking": só 1 envio.
        assert eyes_bridge.set_state("executing") is True
        assert eyes_bridge.set_state("thinking") is False
        assert send_calls["calls"] == ["state thinking"]


# ── 3. speech on/off ────────────────────────────────────────

class TestSpeechLevel:
    def test_entering_speaking_sends_level(self, send_calls):
        assert eyes_bridge.set_state("speaking", speech_level=60) is True
        assert send_calls["calls"] == ["state speaking", "speech 0.60"]

    def test_leaving_speaking_turns_speech_off(self, send_calls):
        eyes_bridge.set_state("speaking", speech_level=60)
        eyes_bridge.set_state("idle")
        assert send_calls["calls"][-2:] == ["state neutral", "speech off"]

    def test_idle_then_thinking_no_spurious_speech_off(self, send_calls):
        eyes_bridge.set_state("idle")
        eyes_bridge.set_state("thinking")
        assert "speech off" not in send_calls["calls"]

    @pytest.mark.parametrize("raw,expected", [
        (None, 0.6),     # default
        (0.85, 0.85),    # já em 0..1
        (60, 0.6),       # volume 0..100
        (250, 1.0),      # clamp alto
        (0, 0.05),       # clamp baixo
        ("bad", 0.6),    # lixo => default
    ])
    def test_norm_speech(self, raw, expected):
        assert eyes_bridge._norm_speech(raw) == pytest.approx(expected)

    def test_env_overrides_default_level(self, monkeypatch, send_calls):
        monkeypatch.setenv("ARIS_EYES_SPEECH_LEVEL", "0.8")
        eyes_bridge.set_state("speaking")
        assert "speech 0.80" in send_calls["calls"]


# ── 4. Falha honesta (olhos parados) ────────────────────────

class TestFailureIsHonest:
    def test_eyes_not_running_returns_false_and_rolls_back(self, monkeypatch):
        monkeypatch.setattr(eyes_bridge, "_client_send", lambda *a, **k: None)
        assert eyes_bridge.set_state("thinking") is False
        assert eyes_bridge.stats()["failed"] == 1
        assert eyes_bridge.stats()["last_state"] is None  # cache desfeito

    def test_retries_on_next_sync_after_failure(self, monkeypatch):
        attempts = []

        def _flaky(command, timeout=0.25, path=None):
            attempts.append(command)
            return None

        monkeypatch.setattr(eyes_bridge, "_client_send", _flaky)
        eyes_bridge.set_state("thinking")
        eyes_bridge.set_state("thinking")   # falhou antes => tenta de novo
        assert len(attempts) == 2

    def test_raising_send_does_not_crash(self, monkeypatch):
        def _boom(command, timeout=0.25, path=None):
            raise RuntimeError("socket explodiu")

        monkeypatch.setattr(eyes_bridge, "_client_send", _boom)
        assert eyes_bridge.set_state("error") is False   # não lançou

    def test_error_response_not_counted_as_ok(self, monkeypatch):
        monkeypatch.setattr(
            eyes_bridge, "_client_send",
            lambda *a, **k: "erro: expressao desconhecida",
        )
        assert eyes_bridge.set_state("thinking") is False

    def test_success_response_is_ok(self, send_calls):
        assert eyes_bridge.set_state("thinking") is True
        assert eyes_bridge.stats()["sent"] == 1


# ── 5. Kill-switch e autolaunch ─────────────────────────────

class TestSwitches:
    def test_kill_switch_disables_everything(self, monkeypatch, send_calls):
        monkeypatch.setenv("ARIS_EYES", "0")
        assert eyes_bridge.set_state("thinking") is False
        assert send_calls["calls"] == []

    def test_probe_uses_ping(self, monkeypatch):
        monkeypatch.setattr(
            eyes_bridge, "_client_send",
            lambda cmd, timeout=0.5: "pong" if cmd == "ping" else "ok",
        )
        assert eyes_bridge.probe() is True

    def test_probe_false_when_offline(self, monkeypatch):
        monkeypatch.setattr(eyes_bridge, "_client_send", lambda *a, **k: None)
        assert eyes_bridge.probe() is False

    def test_autolaunch_once_on_failure(self, monkeypatch):
        monkeypatch.setenv("ARIS_EYES_AUTOLAUNCH", "1")
        monkeypatch.setattr(eyes_bridge, "_client_send", lambda *a, **k: None)
        monkeypatch.setattr(eyes_bridge, "_retry_after_launch", lambda: None)
        pops = []
        monkeypatch.setattr(
            eyes_bridge.subprocess, "Popen",
            lambda *a, **k: pops.append(a) or type("P", (), {"pid": 1})(),
        )
        eyes_bridge.set_state("thinking")
        eyes_bridge.set_state("listening")
        eyes_bridge.set_state("error")
        assert len(pops) == 1              # só UMA tentativa de subir

    def test_no_autolaunch_by_default(self, monkeypatch):
        monkeypatch.setattr(eyes_bridge, "_client_send", lambda *a, **k: None)
        popped = []
        monkeypatch.setattr(
            eyes_bridge.subprocess, "Popen",
            lambda *a, **k: popped.append(a),
        )
        eyes_bridge.set_state("thinking")
        assert popped == []


# ── 6. Personalidade → mood ocioso ──────────────────────────

class TestPersonalityIdleMood:
    @pytest.mark.parametrize("traits,expected", [
        ({"humor": 0.8, "warmth": 0.3}, "happy"),
        ({"humor": 0.3, "warmth": 0.8}, "happy"),
        ({"humor": 0.3, "warmth": 0.3}, "neutral"),
        ({}, "neutral"),                   # defaults 0.5
    ])
    def test_mood_from_personality(self, monkeypatch, send_calls, traits, expected):
        monkeypatch.delenv("ARIS_EYES_IDLE_MOOD")

        class _State:
            pass

        state = _State()
        state.traits = traits
        monkeypatch.setattr(
            "core.personality.get_personality",
            lambda: type("P", (), {"get_state": lambda self: state})(),
        )
        assert eyes_bridge._mood_from_personality() == expected

    def test_forced_idle_mood_env(self, monkeypatch, send_calls):
        monkeypatch.setenv("ARIS_EYES_IDLE_MOOD", "sleepy")
        eyes_bridge.set_state("idle")
        assert send_calls["calls"] == ["state sleepy"]

    def test_refresh_resends_when_idle(self, monkeypatch, send_calls):
        monkeypatch.delenv("ARIS_EYES_IDLE_MOOD")
        monkeypatch.setattr(eyes_bridge, "_mood_from_personality", lambda: "neutral")
        eyes_bridge.refresh_idle_mood()
        eyes_bridge.set_state("idle")
        assert send_calls["calls"] == ["state neutral"]

        # Personalidade mudou (ficou animada) => idle reenviado na hora
        monkeypatch.setattr(eyes_bridge, "_mood_from_personality", lambda: "happy")
        eyes_bridge.refresh_idle_mood()
        assert send_calls["calls"] == ["state neutral", "state happy"]


# ── 7. Hooks no núcleo ──────────────────────────────────────

class TestCoreHooks:
    def test_aris_has_all_eyes_hooks(self):
        from pathlib import Path

        src = Path("core/aris.py").read_text(encoding="utf-8")
        # 5 pontos: sync central, wake word, timer/alerta, shutdown, startup
        assert src.count("eyes_bridge.set_state(") >= 4
        assert "eyes_bridge.refresh_idle_mood()" in src
        assert "eyes_bridge.probe()" in src

    def test_sync_hardware_state_forwards_speech_level(self):
        from pathlib import Path

        src = Path("core/aris.py").read_text(encoding="utf-8")
        seg = src[src.index("def _sync_hardware_state"):]
        seg = seg[:seg.index("\n    def ")]
        assert "speech_level=" in seg
