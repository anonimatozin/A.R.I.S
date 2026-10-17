"""Detector de palmas (duas palmas rápidas) para A.R.I.S.

Detecção baseada em energia/transiente do áudio:
- Transiente = pico de energia que sobe e cai rápido (50-100ms)
- Limiar dinâmico: baseline de ruído + N desvios-padrão
- Duas palmas: dois transientes em janela de 0.3-1.2s
- Cooldown: 2s após detecção
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

# Time provider for testing (can be overridden)
_time_provider = time.monotonic

def _get_time() -> float:
    return _time_provider()

def _set_time_provider(provider: Callable[[], float]) -> Callable[[], float]:
    """Set custom time provider, returns previous provider."""
    global _time_provider
    old = _time_provider
    _time_provider = provider
    return old

import numpy as np

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False
    pyaudio = None  # type: ignore


@dataclass
class ClapDetectorConfig:
    """Configuração do detector de palmas."""
    sample_rate: int = 16000
    frame_duration_ms: int = 30          # Mesmo que VAD (10, 20 ou 30ms)
    calibration_frames: int = 100        # Frames p/ calibrar baseline (~3s a 30ms)
    energy_threshold_multiplier: float = 4.0  # baseline + N * std
    transient_min_ms: int = 60           # 2 frames — palmas medem 60-150ms; blips de ruído ficam em 30ms
    transient_max_ms: int = 250          # palma real mede 120-150ms acima do limiar
    min_peak_rms: float = 0.04           # piso de pico: ruído mede <=0.031, palma real >=0.045
    double_clap_min_gap_ms: int = 300    # Gap mínimo entre palmas (ms)
    double_clap_max_gap_ms: int = 1200   # Gap máximo entre palmas (ms)
    cooldown_ms: int = 2000              # Cooldown após detecção (ms)
    device_index: int = -1               # Índice do microfone (-1 = padrão)


class ClapDetector:
    """Detector de duas palmas rápidas baseado em energia/transiente."""

    def __init__(
        self,
        on_double_clap: Optional[Callable[[], None]] = None,
        config: Optional[ClapDetectorConfig] = None,
        logger=None,
    ) -> None:
        self._config = config or ClapDetectorConfig()
        self._on_double_clap = on_double_clap
        self._logger = logger

        # Estado de calibração
        self._calibration_frames_seen = 0
        self._baseline_energy = 0.0
        self._baseline_std = 0.0
        self._calibrated = False

        # Buffer de energias para calibração
        self._calibration_buffer: list[float] = []

        # Detecção de transientes
        self._in_transient = False
        self._transient_start_time = 0.0
        self._transient_peak_energy = 0.0
        self._transient_frames: list[float] = []

        # Histórico de transientes detectados
        self._transient_times: deque[float] = deque(maxlen=10)

        # Contador de frames do transiente atual
        self._transient_frame_count = 0

        # Cooldown
        self._last_detection_time = -1.0  # Will be set properly in start()

        # Thread e captura
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pyaudio = None
        self._stream = None
        self._mic_token: Optional[int] = None  # vaga no mic compartilhado

        # Frame size
        self._frame_size = int(self._config.sample_rate * self._config.frame_duration_ms / 1000)
        self._bytes_per_frame = self._frame_size * 2  # 16-bit

    @property
    def available(self) -> bool:
        return HAS_PYAUDIO

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    @property
    def threshold(self) -> float:
        return self._baseline_energy + self._config.energy_threshold_multiplier * self._baseline_std

    def start(self) -> bool:
        """Inicia o detector consumindo o mic compartilhado.

        Usa o MicBroadcaster (inicialização única do PortAudio) para não
        conflitar com o sensor de voz contínua — no Linux, abrir um segundo
        PyAudio falhava com "PortAudio can not be initialized recursively".
        """
        if not self.available:
            return False
        if self._running:
            return True

        self._stop_event.clear()
        self._running = True
        self._calibration_frames_seen = 0
        self._calibration_buffer = []
        self._calibrated = False
        self._in_transient = False
        self._transient_times.clear()
        # Inicializar com tempo negativo para não bloquear primeira detecção
        self._last_detection_time = -self._config.cooldown_ms / 1000.0

        # Consome o mic compartilhado (1 stream p/ todo o processo).
        from utils.audio_backend import mic

        token = mic.add_listener(self._process_frame)
        if token < 0:
            self._running = False
            return False
        self._mic_token = token
        return True

    def stop(self) -> None:
        """Para o detector e libera sua vaga no mic compartilhado."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()

        token = getattr(self, "_mic_token", None)
        if token is not None:
            try:
                from utils.audio_backend import mic

                mic.remove_listener(token)
            except Exception:
                pass
            self._mic_token = None

        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _audio_loop(self) -> None:
        """Mantido p/ compatibilidade: o mic agora é compartilhado.

        O ClapDetector recebe frames via callback de listener registrado
        em start(); este loop não é mais usado.
        """
        return

    def _process_frame(self, frame: bytes) -> None:
        """Processa um frame de áudio."""
        if len(frame) != self._bytes_per_frame:
            return

        # Converter para float32 normalizado
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0

        # Energia RMS do frame
        energy = float(np.sqrt(np.mean(audio ** 2)))

        # Calibração inicial
        if not self._calibrated:
            self._calibration_buffer.append(energy)
            self._calibration_frames_seen += 1

            if self._calibration_frames_seen >= self._config.calibration_frames:
                self._finalize_calibration()
            return

        # Detectar transiente
        self._detect_transient(energy)

    def _finalize_calibration(self) -> None:
        """Finaliza calibração do baseline de ruído."""
        if not self._calibration_buffer:
            self._baseline_energy = 0.01
            self._baseline_std = 0.005
        else:
            arr = np.array(self._calibration_buffer)
            # descarta os 20% mais altos: uma palma durante a calibração
            # inflava std e empurrava o limiar acima do pico da própria palma
            limit = float(np.percentile(arr, 80))
            clean = arr[arr <= limit] if (arr <= limit).any() else arr
            self._baseline_energy = float(np.mean(clean))
            self._baseline_std = float(np.std(clean))
            # Evitar std zero
            if self._baseline_std < 1e-6:
                self._baseline_std = 1e-6

        self._calibrated = True
        if self._logger:
            self._logger.debug(
                f"ClapDetector: calibrado baseline={self._baseline_energy:.6f} "
                f"std={self._baseline_std:.6f} threshold={self.threshold:.6f}"
            )

    def _detect_transient(self, energy: float) -> None:
        """Detecta transientes (picos curtos de energia)."""
        threshold = self.threshold
        now = _get_time()

        if energy > threshold:
            # Início ou continuação de transiente
            if not self._in_transient:
                self._in_transient = True
                self._transient_start_time = now
                self._transient_frame_count = 0
                self._transient_peak_energy = energy
                self._transient_frames = [energy]
            else:
                self._transient_peak_energy = max(self._transient_peak_energy, energy)
                self._transient_frames.append(energy)
            self._transient_frame_count += 1
        else:
            # Fim de transiente (energia caiu abaixo do limiar)
            if self._in_transient:
                # Calcular duração baseada em contagem de frames (mais confiável)
                duration_ms = self._transient_frame_count * self._config.frame_duration_ms

                # Verificar se é um transiente válido (60-250ms) e forte o bastante
                if self._config.transient_min_ms <= duration_ms <= self._config.transient_max_ms:
                    if self._transient_peak_energy >= self._config.min_peak_rms:
                        self._register_transient(now)

                self._in_transient = False
                self._transient_frames = []
                self._transient_frame_count = 0

        # Timeout de transiente longo demais (não é palma)
        if self._in_transient:
            duration_ms = self._transient_frame_count * self._config.frame_duration_ms
            if duration_ms > self._config.transient_max_ms * 1.5:
                self._in_transient = False
                self._transient_frames = []
                self._transient_frame_count = 0

    def _register_transient(self, timestamp: Optional[float] = None) -> None:
        """Registra um transiente válido e verifica se forma dupla palma."""
        if timestamp is None:
            timestamp = _get_time()
        # Verificar cooldown
        if timestamp - self._last_detection_time < self._config.cooldown_ms / 1000:
            return

        self._transient_times.append(timestamp)

        # Verificar se há dois transientes na janela
        if len(self._transient_times) >= 2:
            # Pegar os dois mais recentes
            t1 = self._transient_times[-2]
            t2 = self._transient_times[-1]
            gap_ms = (t2 - t1) * 1000

            if self._config.double_clap_min_gap_ms <= gap_ms <= self._config.double_clap_max_gap_ms:
                self._trigger_double_clap()
                self._last_detection_time = timestamp
                self._transient_times.clear()

    def _trigger_double_clap(self) -> None:
        """Dispara callback de dupla palma detectada."""
        if self._on_double_clap:
            try:
                self._on_double_clap()
            except Exception:
                pass

    def set_callback(self, callback: Callable[[], None]) -> None:
        """Define callback para dupla palma."""
        self._on_double_clap = callback


# ─── Testes com áudio sintético ───

# Mock time for synthetic tests
_mock_time = 0.0
_time_advance_per_frame = 0.03  # 30ms per frame

def _mock_time_provider() -> float:
    global _mock_time
    return _mock_time

def _advance_mock_time(frames: int = 1) -> None:
    global _mock_time
    _mock_time += _time_advance_per_frame * frames

def _reset_mock_time() -> None:
    global _mock_time
    _mock_time = 0.0

def _generate_test_frame(energy: float, frame_size: int, sample_rate: int = 16000) -> bytes:
    """Gera frame sintético com energia RMS específica."""
    noise = np.random.normal(0, 1, frame_size).astype(np.float32)
    current_energy = np.sqrt(np.mean(noise ** 2))
    if current_energy > 0:
        noise = noise * (energy / current_energy)
    audio_int16 = np.clip(noise * 32767, -32768, 32767).astype(np.int16)
    return audio_int16.tobytes()


def _generate_transient_frame(peak_energy: float, frame_size: int, sample_rate: int = 16000) -> bytes:
    """Gera frame com transiente (pico rápido) - energia RMS ~peak_energy."""
    t = np.linspace(0, np.pi, frame_size)
    envelope = np.sin(t)
    noise = np.random.normal(0, 1, frame_size).astype(np.float32)
    rms_envelope = np.sqrt(np.mean(envelope ** 2))
    noise = noise * envelope * (peak_energy / rms_envelope)
    audio_int16 = np.clip(noise * 32767, -32768, 32767).astype(np.int16)
    return audio_int16.tobytes()


def _patch_detector_time(detector: ClapDetector) -> None:
    """Substitui time provider do detector por mock controlado."""
    detector._original_time_provider = _set_time_provider(_mock_time_provider)


def _unpatch_detector_time(detector: ClapDetector) -> None:
    """Restaura time provider original."""
    if hasattr(detector, '_original_time_provider'):
        _set_time_provider(detector._original_time_provider)


def test_clap_detector() -> None:
    """Testa o detector com áudio sintético nos 4 cenários."""
    print("=" * 60)
    print("TESTE DO CLAP DETECTOR (audio sintetico)")
    print("=" * 60)

    config = ClapDetectorConfig(
        calibration_frames=10,
        energy_threshold_multiplier=3.0,
    )
    detector = ClapDetector(config=config)

    # Patch time for synthetic test
    _patch_detector_time(detector)
    _reset_mock_time()

    frame_size = detector._frame_size
    frames_per_sec = 1000 // config.frame_duration_ms

    detected = {"count": 0}

    def on_clap():
        detected["count"] += 1
        print(f"  >>> DUPLA PALMA DETECTADA! (total: {detected['count']})")

    detector.set_callback(on_clap)

    # Initialize detector state for synthetic test (without starting audio thread)
    detector._calibrated = False
    detector._calibration_frames_seen = 0
    detector._calibration_buffer = []
    detector._in_transient = False
    detector._transient_times.clear()
    detector._transient_frame_count = 0
    detector._last_detection_time = -detector._config.cooldown_ms / 1000.0

    # Helper to process frames with time advance
    def process_frames(frames: list[bytes], advance: bool = True):
        for frame in frames:
            detector._process_frame(frame)
            if advance:
                _advance_mock_time(1)

    # [1] CALIBRACAO
    print("\n[1] CALIBRACAO - Ruido de fundo baixo")
    cal_frames = [_generate_test_frame(0.005, frame_size) for _ in range(config.calibration_frames)]
    process_frames(cal_frames)
    print(f"  Baseline: {detector._baseline_energy:.6f}, Std: {detector._baseline_std:.6f}, Threshold: {detector.threshold:.6f}")
    assert detector.calibrated, "Deveria estar calibrado"

    test_frame = _generate_transient_frame(0.5, frame_size)
    audio = np.frombuffer(test_frame, dtype=np.int16).astype(np.float32) / 32768.0
    test_energy = float(np.sqrt(np.mean(audio ** 2)))
    print(f"  Transient frame energy: {test_energy:.6f} (threshold: {detector.threshold:.6f})")

    # [2] CENARIO A: Uma palma so
    print("\n[2] CENARIO A: Uma palma so (NAO deve disparar)")
    detected["count"] = 0
    detector._transient_times.clear()
    _reset_mock_time()

    palm_frames = [_generate_transient_frame(0.5, frame_size) for _ in range(3)]
    process_frames(palm_frames)
    silence_frames = [_generate_test_frame(0.005, frame_size) for _ in range(10)]
    process_frames(silence_frames)

    print(f"  Transient times: {list(detector._transient_times)}")
    print(f"  Detecções: {detected['count']} (esperado: 0)")
    assert detected["count"] == 0, "Palma unica nao deve disparar"

    # [3] CENARIO B: Duas palmas rapidas
    print("\n[3] CENARIO B: Duas palmas rapidas (DEVE disparar)")
    detected["count"] = 0
    detector._transient_times.clear()
    _reset_mock_time()

    palm1 = [_generate_transient_frame(0.5, frame_size) for _ in range(3)]
    process_frames(palm1)
    gap_frames = [_generate_test_frame(0.005, frame_size) for _ in range(17)]
    process_frames(gap_frames)
    palm2 = [_generate_transient_frame(0.5, frame_size) for _ in range(3)]
    process_frames(palm2)
    end_silence = [_generate_test_frame(0.005, frame_size) for _ in range(10)]
    process_frames(end_silence)

    print(f"  Transient times: {[f'{t:.3f}' for t in detector._transient_times]}")
    print(f"  Detecções: {detected['count']} (esperado: 1)")
    assert detected["count"] == 1, "Duas palmas rapidas devem disparar"

    # [4] CENARIO C: Duas palmas espaçadas >1.2s
    print("\n[4] CENARIO C: Duas palmas espacadas >1.2s (NAO deve disparar)")
    detected["count"] = 0
    detector._transient_times.clear()
    _reset_mock_time()

    palm1 = [_generate_transient_frame(0.5, frame_size) for _ in range(3)]
    process_frames(palm1)
    gap_frames = [_generate_test_frame(0.005, frame_size) for _ in range(67)]
    process_frames(gap_frames)
    palm2 = [_generate_transient_frame(0.5, frame_size) for _ in range(3)]
    process_frames(palm2)
    end_silence = [_generate_test_frame(0.005, frame_size) for _ in range(10)]
    process_frames(end_silence)

    print(f"  Transient times: {[f'{t:.3f}' for t in detector._transient_times]}")
    print(f"  Detecções: {detected['count']} (esperado: 0)")
    assert detected["count"] == 0, "Palmas muito espacadas nao devem disparar"

    # [5] CENARIO D: Ruido sustentado alto
    print("\n[5] CENARIO D: Ruido sustentado alto (fala/musica) (NAO deve disparar)")
    detected["count"] = 0
    detector._transient_times.clear()
    _reset_mock_time()

    sustained_frames = [_generate_test_frame(0.3, frame_size) for _ in range(frames_per_sec * 2)]
    process_frames(sustained_frames)

    print(f"  Transient times: {list(detector._transient_times)}")
    print(f"  Detecções: {detected['count']} (esperado: 0)")
    assert detected["count"] == 0, "Ruido sustentado nao deve disparar"

    _unpatch_detector_time(detector)

    print("\n" + "=" * 60)
    print("TODOS OS TESTES PASSARAM!")
    print("=" * 60)


if __name__ == "__main__":
    test_clap_detector()