"""Voz feminina pt-BR: espeak (pt-br+f3) e piper (pt_BR-faber-medium).

Verificação OBJETIVA por análise de pitch (F0 mediana do wav gerado):
a voz antiga do espeak (`pt-br`) media ~108 Hz (masculina); as novas
medem ~160–215 Hz. O threshold dos testes é 140 Hz — separa os dois
mundos com folga.
"""

from __future__ import annotations

import shutil
import subprocess
import wave

import numpy as np
import pytest

from utils.voice_hybrid import HybridVoice

FEMALE_F0_MIN = 140  # Hz — voz masculina antiga media 108; femininas > 155


def _bare_voice() -> HybridVoice:
    """HybridVoice sem TTS/STT/mic reais (mesmo padrão do test_voice_fase4)."""
    v = HybridVoice.__new__(HybridVoice)
    v._rate = 0
    v._volume = 100
    v._language = "pt-BR"
    v._enabled = True
    v._tts_engine = "edge-tts"
    v._logger = None
    v._stop_requested = False
    return v


def _f0_median(path: str) -> float | None:
    """F0 mediana (Hz) dos frames vozeados do wav — autocorrelação."""
    w = wave.open(path)
    sr = w.getframerate()
    x = np.frombuffer(
        w.readframes(w.getnframes()), dtype=np.int16
    ).astype(np.float32)
    if w.getnchannels() > 1:
        x = x.reshape(-1, w.getnchannels()).mean(axis=1)
    win, hop = int(sr * 0.04), int(sr * 0.02)
    found: list[float] = []
    for i in range(0, len(x) - win, hop):
        frame = x[i:i + win]
        if float(np.sqrt((frame ** 2).mean())) < 80:
            continue
        ac = np.correlate(frame, frame, "full")[win - 1:]
        lo, hi = sr // 400, sr // 60
        if hi >= len(ac):
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0:
            found.append(sr / lag)
    if not found:
        return None
    return float(np.median(found))


@pytest.fixture
def played(monkeypatch, tmp_path):
    """Intercepta os wavs (copia p/ tmp antes do método apagar o original)."""
    paths: list[str] = []

    def _fake_play(self, path: str) -> bool:
        keep = tmp_path / f"speech_{len(paths)}.wav"
        shutil.copy(path, keep)
        paths.append(str(keep))
        return True

    monkeypatch.setattr(HybridVoice, "_play_wav", _fake_play)
    return paths


@pytest.fixture
def run_spy(monkeypatch):
    """Espiona subprocess.run mas deixa o processo rodar de verdade."""
    calls: list[list[str]] = []
    real = subprocess.run

    def _spy(cmd, **kwargs):
        calls.append(list(cmd))
        return real(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy)
    return calls


# ── espeak-ng ───────────────────────────────────────────────

class TestEspeakFemale:
    def test_default_voice_is_female_variant(self, played, run_spy):
        v = _bare_voice()
        assert v._speak_espeak("Bom dia, eu sou a A R I S.") is True
        argv = run_spy[0]
        assert argv[argv.index("-v") + 1] == "pt-br+f3"

    def test_env_can_override_voice(self, monkeypatch, played, run_spy):
        monkeypatch.setenv("ARIS_ESPEAK_VOICE", "pt-br+f5")
        v = _bare_voice()
        assert v._speak_espeak("Teste.") is True
        argv = run_spy[0]
        assert argv[argv.index("-v") + 1] == "pt-br+f5"

    def test_generated_wav_is_female_pitch(self, played, run_spy):
        v = _bare_voice()
        assert v._speak_espeak("Teste de voz feminina da ARIS.") is True
        assert played, "wav não foi tocado/copiado"
        f0 = _f0_median(played[0])
        assert f0 is not None, "sem frames vozeados"
        assert f0 > FEMALE_F0_MIN, f"espeak ficou em {f0:.0f} Hz (esperado feminino)"


# ── piper ───────────────────────────────────────────────────

class TestPiperFemale:
    def test_default_model_discovered(self):
        model = HybridVoice._default_piper_voice()
        assert model.endswith("pt_BR-faber-medium.onnx")

    @pytest.mark.skipif(
        not HybridVoice._default_piper_voice(),
        reason="modelo piper pt_BR-faber-medium não baixado",
    )
    def test_synth_uses_female_model_and_wav_is_female(
        self, monkeypatch, played, run_spy,
    ):
        monkeypatch.delenv("ARIS_PIPER_VOICE", raising=False)
        v = _bare_voice()
        assert v._speak_piper("Teste de voz feminina da ARIS.") is True
        assert played, "wav não foi tocado/copiado"

        argv = run_spy[0]
        assert "--model" in argv
        model_used = argv[argv.index("--model") + 1]
        assert model_used.endswith("pt_BR-faber-medium.onnx")

        f0 = _f0_median(played[0])
        assert f0 is not None, "sem frames vozeados"
        assert f0 > FEMALE_F0_MIN, f"piper ficou em {f0:.0f} Hz (esperado feminino)"

    @pytest.mark.skipif(
        not HybridVoice._default_piper_voice(),
        reason="modelo piper pt_BR-faber-medium não baixado",
    )
    def test_fallback_order_piper_first(self):
        # Sem edge (403) → offline tenta piper ANTES do espeak.
        assert HybridVoice._find_piper() is not None
