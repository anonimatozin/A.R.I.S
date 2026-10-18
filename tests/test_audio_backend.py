"""Testes do backend de captação compartilhado (utils/audio_backend).

Cobre o fallback ``arecord`` — o caminho REAL deste ambiente, onde o
PyAudio está quebrado (sem módulo C) e não há libportaudio:

- sem NENHUM backend, ``add_listener`` devolve -1 (sem fantasma);
- com arecord (fake), frames exatos de ``frame_size * 2`` bytes chegam
  aos listeners;
- EOF do arecord (device sumiu) → respawn automático sem derrubar os
  listeners;
- micro que não abre → -1 e registro removido;
- integração real com o micro (pula se não houver arecord/dispositivo).
"""

from __future__ import annotations

import io
import os
import shutil
import struct
import subprocess
import threading
import types
import wave

import numpy as np
import pytest

from utils import audio_backend
from utils.audio_backend import MicBroadcaster

FRAME_MS = 30
RATE = 16000
FRAME_BYTES = int(RATE * FRAME_MS / 1000) * 2  # s16le mono


# ── Fakes ───────────────────────────────────────────────────

class _FakeProc:
    """Processo arecord falso: stdout é um BytesIO (frames p/ ler)."""

    def __init__(self, payload: bytes = b"") -> None:
        self.stdout = io.BytesIO(payload)
        self.returncode: int | None = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout: float | None = None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def _fake_subprocess(popen_factory):
    """Namespace p/ monkeypatch: só o Popen é usado pelo backend."""
    return types.SimpleNamespace(
        Popen=popen_factory, PIPE=object(), DEVNULL=object(),
    )


def _wait_frames(frames, minimum=1, timeout=3.0) -> bool:
    deadline = threading.Event()
    end = timeout
    waited = 0.0
    while waited < end:
        if len(frames) >= minimum:
            return True
        deadline.wait(0.01)
        waited += 0.01
    return len(frames) >= minimum


# ── 1. Sem backend nenhum ───────────────────────────────────

def test_no_backend_returns_minus_one(monkeypatch):
    monkeypatch.setattr(audio_backend, "HAS_PYAUDIO", False)
    monkeypatch.setattr(audio_backend, "HAS_CAPTURE", False)
    monkeypatch.setattr(audio_backend, "_ARECORD", None)
    mic = MicBroadcaster()
    token = mic.add_listener(lambda data: None)
    assert token == -1
    assert mic.listener_count == 0
    assert mic.running is False


# ── 2. Fallback arecord entrega frames ──────────────────────

def test_arecord_backend_delivers_exact_frames(monkeypatch):
    monkeypatch.setattr(audio_backend, "HAS_PYAUDIO", False)
    monkeypatch.setattr(audio_backend, "HAS_CAPTURE", True)
    monkeypatch.setattr(audio_backend, "_ARECORD", "/usr/bin/arecord")

    payload = (b"\x01\x02" * (FRAME_BYTES // 2)) * 4
    monkeypatch.setattr(
        audio_backend, "subprocess",
        _fake_subprocess(lambda *a, **k: _FakeProc(payload)),
    )

    frames: list[bytes] = []
    mic = MicBroadcaster(frame_duration_ms=FRAME_MS)
    try:
        token = mic.add_listener(frames.append)
        assert token >= 0, "com arecord fake o token deve ser válido"
        assert mic.running is True
        assert _wait_frames(frames, minimum=2), "nenhum frame chegou"
        assert all(len(f) == FRAME_BYTES for f in frames)
        assert all(f == payload[:FRAME_BYTES] for f in frames)
    finally:
        if token >= 0:
            mic.remove_listener(token)
    assert mic.running is False
    assert mic.listener_count == 0


# ── 3. EOF (device caiu) → respawn sem perder listeners ────

def test_eof_respawns_arecord(monkeypatch):
    import itertools

    monkeypatch.setattr(audio_backend, "HAS_PYAUDIO", False)
    monkeypatch.setattr(audio_backend, "HAS_CAPTURE", True)
    monkeypatch.setattr(audio_backend, "_ARECORD", "/usr/bin/arecord")

    payload = (b"\x11\x22" * (FRAME_BYTES // 2)) * 3
    spawns = []
    # 1º processo morre na hora (EOF vazio); 2º entrega frames; ciclo repete.
    procs = itertools.cycle([_FakeProc(b""), _FakeProc(payload)])

    def _factory(*a, **k):
        spawns.append(1)
        return next(procs)

    monkeypatch.setattr(audio_backend, "subprocess", _fake_subprocess(_factory))

    frames: list[bytes] = []
    mic = MicBroadcaster(frame_duration_ms=FRAME_MS)
    try:
        token = mic.add_listener(frames.append)
        assert token >= 0
        assert _wait_frames(frames, minimum=2), "respawn não entregou frames"
        assert len(spawns) >= 2, "arecord não renasceu após o EOF"
        assert all(len(f) == FRAME_BYTES for f in frames)
    finally:
        if token >= 0:
            mic.remove_listener(token)


# ── 4. Micro que não abre → -1 honesto (sem fantasma) ───────

def test_failed_open_returns_minus_one(monkeypatch):
    monkeypatch.setattr(audio_backend, "HAS_PYAUDIO", False)
    monkeypatch.setattr(audio_backend, "HAS_CAPTURE", True)
    monkeypatch.setattr(audio_backend, "_ARECORD", "/usr/bin/arecord")

    def _dead_proc(*a, **k):
        proc = _FakeProc(b"")
        proc.returncode = 1  # morreu na hora (device ocupado)
        return proc

    monkeypatch.setattr(audio_backend, "subprocess", _fake_subprocess(_dead_proc))

    mic = MicBroadcaster()
    token = mic.add_listener(lambda data: None)
    assert token == -1
    assert mic.listener_count == 0, "listener fantasma não pode sobrar"
    assert mic.running is False


# ── 5. Sensor de voz contínua: available via fallback ───────
#
# Regressão do bug real: `available` checava o pyaudio (quebrado neste
# ambiente) e derrubava o sensor INTEIRO ("Sensor desabilitado ou
# dependências faltando") — a ARIS ficava surda em todos os modos.


def _make_sensor():
    from core.perception.continuous_voice_sensor import (
        ContinuousVoiceConfig,
        ContinuousVoiceSensor,
    )

    return ContinuousVoiceSensor(
        send_message_fn=lambda *a, **k: None,
        config=ContinuousVoiceConfig(enabled=True),
    )


def test_voice_sensor_available_via_capture_fallback(monkeypatch):
    monkeypatch.setattr(audio_backend, "HAS_CAPTURE", True)
    sensor = _make_sensor()
    assert sensor.available is True, "fallback arecord deve contar como disponível"
    assert sensor.enabled is True


def test_voice_sensor_unavailable_without_any_capture(monkeypatch):
    monkeypatch.setattr(audio_backend, "HAS_CAPTURE", False)
    sensor = _make_sensor()
    assert sensor.available is False
    assert sensor.enabled is False


# ── 6. Integração real: micro de verdade ────────────────────

@pytest.mark.skipif(not audio_backend._ARECORD, reason="arecord ausente")
def test_real_arecord_captures_signal():
    frames: list[bytes] = []
    mic = MicBroadcaster(frame_duration_ms=FRAME_MS)
    token = mic.add_listener(frames.append)
    if token < 0:
        pytest.skip("micro indisponível/ocupado neste ambiente")
    try:
        assert _wait_frames(frames, minimum=3, timeout=4.0), (
            "arecord real não entregou frames em 4s"
        )
        assert all(len(f) == FRAME_BYTES for f in frames[:10])
        # Sinal não-trivial: algum sample com amplitude > 0.
        joined = b"".join(frames[:5])
        samples = struct.unpack(f"<{len(joined) // 2}h", joined)
        assert max(abs(s) for s in samples) > 0, "apenas silêncio digital"
    finally:
        mic.remove_listener(token)


# ── 7. VAD: gate de energia (regressão: utterância presa) ───
#
# Bug real: o webrtcvad flickerava ~1 frame/s de "fala" no chiado do
# mic (RMS medido ~472) — o contador de silêncio nunca chegava a 40
# frames (1,2s) e a utterância ficava presa até o limite de 30s
# (execução real: 112s / 3,5 MB de buffer), engolindo as frases do
# usuário: a wake word nunca era processada.


def _noisy_frame(rms: float, seed: int = 7) -> bytes:
    """Frame sintético 16k/30ms com RMS alvo (chiado do mic ~472)."""
    rng = np.random.default_rng(seed)
    return rng.normal(0, rms, 480).clip(-32768, 32767).astype(np.int16).tobytes()


def test_vad_gate_rejects_mic_hiss():
    sensor = _make_sensor()
    assert sensor._is_speech(_noisy_frame(450)) is False, (
        "chiado (RMS 450 < 750) não pode sustentar a utterância"
    )


def test_vad_gate_rejects_digital_silence():
    sensor = _make_sensor()
    assert sensor._is_speech(b"\x00" * FRAME_BYTES) is False


def test_vad_gate_rejects_loud_enviroment_below_threshold():
    sensor = _make_sensor()
    # Ambiente real medido: p90 = 520 (0% dos frames passam de 750).
    assert sensor._is_speech(_noisy_frame(520, seed=11)) is False


@pytest.mark.skipif(not shutil.which("espeak-ng"), reason="espeak-ng ausente")
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_vad_gate_accepts_real_speech(tmp_path):
    """Voz real sintetizada (espeak→16k) precisa passar gate+VAD."""
    raw = tmp_path / "fala_22k.wav"
    wav = tmp_path / "fala_16k.wav"
    subprocess.run(
        ["espeak-ng", "-v", "pt-br+f3", "-s", "160", "-w", str(raw),
         "Aris, tudo bem com você?"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-v", "quiet", "-y", "-i", str(raw),
         "-ar", str(RATE), "-ac", "1", str(wav)],
        check=True, capture_output=True,
    )
    w = wave.open(str(wav))
    samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    n = RATE // 1000 * 30
    frames = [samples[i:i + n].tobytes() for i in range(0, len(samples) - n, n)]

    sensor = _make_sensor()
    positives = sum(1 for f in frames if sensor._is_speech(f) is True)
    assert len(frames) >= 20, "síntese curta demais para avaliar"
    assert positives >= 10, (
        f"só {positives}/{len(frames)} frames de voz real aceitos"
    )


# ── 8. STT loop: fechamento da utterância (ms ≠ frames) ─────
#
# Bug real: `effective_silence_limit` usava `silence_timeout_ms` (1200,
# em MILISSEGUNDOS) comparado com a contagem de FRAMES — a utterância
# exigia 36s de silêncio para fechar (deveria ser 1,2s), e as frases
# do usuário se misturavam em buffers gigantes.


def test_stt_loop_closes_utterance_after_configured_silence(monkeypatch):
    from core.perception.continuous_voice_sensor import (
        ContinuousVoiceConfig,
        ContinuousVoiceSensor,
    )

    # silence_timeout_ms=90 → fechar após 3 frames (30ms cada).
    # Com o bug (ms tratado como frames) seriam 90 frames de silêncio.
    config = ContinuousVoiceConfig(
        enabled=True,
        silence_timeout_ms=90,
        min_speech_ms=60,
        warmup_frames=0,
    )
    sensor = ContinuousVoiceSensor(
        send_message_fn=lambda *a, **k: None, config=config,
    )

    processed: list[int] = []
    monkeypatch.setattr(
        sensor, "_process_speech_buffer",
        lambda: processed.append(1) or True,
    )

    # Fala: gaussian RMS 2000 passa no gate E no webrtcvad (medido: 100/100).
    sensor._audio_queue.put(_noisy_frame(2000, seed=3))
    sensor._audio_queue.put(_noisy_frame(2000, seed=4))
    sensor._audio_queue.put(_noisy_frame(2000, seed=5))
    # Silêncio/chiado: rejeitado pelo gate de energia.
    for seed in range(10):
        sensor._audio_queue.put(_noisy_frame(450, seed=100 + seed))
    sensor._audio_queue.put(b"")  # sentinela: encerra o loop

    sensor._running = True
    thread = threading.Thread(target=sensor._stt_loop, daemon=True)
    thread.start()
    thread.join(timeout=5.0)
    sensor._running = False

    assert processed == [1], (
        "utterância não fechou após o silêncio configurado "
        f"(processou {len(processed)}x; com o bug seriam 90 frames/2,7s+)"
    )


# ── 9. Wake word: fuzzy tolerante (whisper ouve "Ares") ─────
#
# Bug real medido ao vivo (12:50): o whisper tiny transcreveu o nome
# do usuário como "Ares" (não "Aris") — a lista fixa ('aris', ...)
# não casava e o comando era descartado em silêncio. Correção:
# tolerância a 1 edição de distância por palavra (≥4 letras).


def test_wake_word_fuzzy_matches_whisper_homophone():
    sensor = _make_sensor()
    # O homófono medido no run real ("Ares") e o nome correto
    assert sensor._match_wake_word("Ares, tudo bem?") is True
    assert sensor._match_wake_word("Aris, tudo bem?") is True
    # Transcript REAL do usuário captado no run ao vivo (12:50) — caso medido
    assert sensor._match_wake_word(
        "Ares você não está falando em voz  Ares está aí  Ares, tudo bem"
    ) is True
    # Substring NÃO acorda mais (correção da wake word por palavra inteira:
    # "arista"/"arisco" são outras palavras — ver tests/test_wake_word.py)
    assert sensor._match_wake_word("Arista aí") is False
    # Acento normalizado
    assert sensor._match_wake_word(" oi arís ") is True


def test_wake_word_fuzzy_rejects_unrelated_speech():
    sensor = _make_sensor()
    assert sensor._match_wake_word("bares do centro") is False
    # Contém "ari" mas distância real > 1 edição
    assert sensor._match_wake_word("claridade total") is False
    assert sensor._match_wake_word("bom dia pessoal") is False
    assert sensor._match_wake_word("") is False


def test_stage2_delivers_fuzzy_homophone(monkeypatch):
    """Regressão Bug A: a ETAPA 2 (_on_transcript_result) que ENTREGA o
    comando precisa usar o MESMO match fuzzy da etapa 1.

    Bug real: a etapa 1 passava (fuzzy) mas a etapa 2 ainda era match
    exato — quando o whisper ouvia "Ares" (não "Aris") o comando era
    descartado em silêncio na entrega ("às vezes ela não responde").
    """
    sensor = _make_sensor()
    sensor._last_wake_time = 0.0  # fora do cooldown
    delivered: list[str] = []
    monkeypatch.setattr(
        sensor, "_send_message",
        lambda text, origin=None: delivered.append(text),
    )

    # Caso real medido: whisper ouve "Ares" — ANTES rejeitado aqui
    assert sensor._on_transcript_result("Ares, tudo bem com você?") is True
    assert delivered == ["Ares, tudo bem com você?"]

    # Nome correto também entrega (cooldown resetado = falas separadas)
    delivered.clear()
    sensor._last_wake_time = 0.0
    assert sensor._on_transcript_result("Aris, que horas são?") is True
    assert delivered == ["Aris, que horas são?"]

    # Sem wake word → não entrega (cooldown de T2 permanece ativo)
    delivered.clear()
    assert sensor._on_transcript_result("bares do centro") is False
    assert delivered == []

    # Cooldown ativo (1s) bloquea re-trigger imediato — regressão preservada
    delivered.clear()
    assert sensor._on_transcript_result("Aris, tudo bem?") is False
    assert delivered == []


# ── 10. Instância única (duas cópias brigam pelo microfone) ───

def test_single_instance_lock_is_exclusive(monkeypatch, tmp_path):
    """Duas instâncias simultâneas = dois ``arecord`` disputando o
    dispositivo ALSA ``default`` (exclusivo para captura) → uma delas
    fica surda e "às vezes não responde" (bug medido às 13:26).

    A trava por flock deve ser mutuamente exclusiva até entre dois
    descritores do MESMO processo (open()s independentes).
    """
    import aris_local

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    aris_local._release_instance_lock()  # estado limpo

    assert aris_local._acquire_instance_lock() is None       # 1ª ganha
    holder = aris_local._acquire_instance_lock()             # 2ª perde
    assert holder == os.getpid()  # PID gravado dentro do lock file

    aris_local._release_instance_lock()
    assert aris_local._acquire_instance_lock() is None       # liberou
    aris_local._release_instance_lock()


def test_find_other_instance_smoke():
    """Varredura de /proc não pode quebrar e devolve None ou PID válido.

    Nenhuma instância real do aris_local roda dentro da suíte, então o
    caso comum é None — mas aceita int se uma instância existir fora.
    """
    import aris_local

    result = aris_local._find_other_instance()
    assert result is None or (isinstance(result, int) and result > 0)
