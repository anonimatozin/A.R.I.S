"""Seleção automática de microfone por SNR (Signal-to-Noise Ratio).

Detecta todos os dispositivos de entrada disponíveis, mede o nível de sinal
e ruído de cada um, e seleciona o melhor automaticamente.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    import pyaudio
    import numpy as np
    HAS_PYAUDIO = True
except ImportError:
    pyaudio = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    HAS_PYAUDIO = False


@dataclass
class MicDevice:
    """Informações de um dispositivo de microfone."""
    index: int
    name: str
    channels: int
    sample_rate: int
    snr_db: float = 0.0
    signal_level: float = 0.0
    noise_level: float = 0.0
    is_default: bool = False


class MicSelector:
    """
    Seletor automático de microfone por SNR.

    Funcionamento:
    1. Enumera todos os dispositivos de entrada disponíveis
    2. Para cada dispositivo, grava uma amostra curta (1-2s)
    3. Calcula SNR = 20 * log10(signal_rms / noise_rms)
    4. Seleciona o dispositivo com maior SNR
    5. Reavalia periodicamente (padrão: a cada 30min)
    """

    def __init__(
        self,
        logger: Any = None,
        sample_duration: float = 1.5,
        reevaluate_interval: float = 1800.0,  # 30 min
        sample_rate: int = 16000,
        chunk_size: int = 1024,
    ) -> None:
        self._logger = logger
        self._sample_duration = sample_duration
        self._reevaluate_interval = reevaluate_interval
        self._sample_rate = sample_rate
        self._chunk_size = chunk_size

        self._devices: list[MicDevice] = []
        self._best_device: Optional[MicDevice] = None
        self._lock = threading.Lock()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def available(self) -> bool:
        return HAS_PYAUDIO

    @property
    def best_device(self) -> Optional[MicDevice]:
        with self._lock:
            return self._best_device

    def start(self) -> bool:
        """Inicia seleção automática e reavaliação periódica."""
        if not self.available:
            self._log("warning", "PyAudio não disponível - seleção de microfone desabilitada")
            return False
        if self._running:
            return True

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="mic-selector", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Para o seletor."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _log(self, level: str, message: str) -> None:
        if self._logger:
            getattr(self._logger, level, print)(f"[MIC/SELECTOR] {message}")

    def _run_loop(self) -> None:
        """Loop principal: avalia uma vez e depois periodicamente."""
        self._evaluate_all()

        while self._running:
            if self._stop_event.wait(timeout=self._reevaluate_interval):
                break
            if self._running:
                self._evaluate_all()

    def _evaluate_all(self) -> None:
        """Avalia todos os dispositivos e atualiza o melhor."""
        try:
            devices = self._enumerate_devices()
            if not devices:
                self._log("warning", "Nenhum dispositivo de entrada encontrado")
                return

            evaluated = []
            for device in devices:
                try:
                    snr = self._measure_snr(device)
                    device.snr_db = snr
                    evaluated.append(device)
                except Exception as exc:
                    self._log("warning", f"Falha ao avaliar {device.name}: {exc}")

            if not evaluated:
                return

            # Ordenar por SNR (maior primeiro)
            evaluated.sort(key=lambda d: d.snr_db, reverse=True)

            with self._lock:
                old_best = self._best_device
                self._devices = evaluated
                self._best_device = evaluated[0]

                if old_best is None or old_best.index != self._best_device.index:
                    self._log(
                        "info",
                        f"Melhor microfone: {self._best_device.name} (SNR: {self._best_device.snr_db:.1f} dB)"
                    )

        except Exception as exc:
            self._log("warning", f"Erro na avaliação de microfones: {exc}")

    def _enumerate_devices(self) -> list[MicDevice]:
        """Lista todos os dispositivos de entrada disponíveis."""
        if not HAS_PYAUDIO:
            return []

        # Linux: usa apenas o device de entrada padrão (gerenciado pelo
        # PipeWire/PulseAudio). Abrir os devices ALSA "hw:*" diretamente
        # derruba o PortAudio (abort/segfault em C) quando o servidor de
        # áudio já os detém — e é o mesmo device que o speech_recognition
        # usa por padrão.
        if sys.platform == "linux":
            pa = pyaudio.PyAudio()
            try:
                try:
                    info = pa.get_default_input_device_info()
                except Exception:
                    info = None
                if not info:
                    return []
                return [
                    MicDevice(
                        index=int(info.get("index", -1)),
                        name=info.get("name", "default"),
                        channels=1,
                        sample_rate=int(
                            info.get("defaultSampleRate", self._sample_rate)
                        ),
                        is_default=True,
                    )
                ]
            finally:
                pa.terminate()

        devices = []
        pa = pyaudio.PyAudio()
        try:
            default_input = pa.get_default_input_device_info()
            default_index = default_input.get("index", -1)
        except Exception:
            default_index = -1

        try:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                max_in = int(info.get("maxInputChannels", 0))
                # Pula roteadores/patches (pipewire, default, sysdefault...):
                # reportam dezenas de canais e, no Linux, o PortAudio aborta
                # (SIGABRT em C) ao tentar abrir streams com tantos canais.
                if max_in > 2:
                    continue
                if max_in > 0:
                    device = MicDevice(
                        index=i,
                        name=info.get("name", f"Device {i}"),
                        channels=max_in,
                        sample_rate=int(info.get("defaultSampleRate", self._sample_rate)),
                        is_default=(i == default_index),
                    )
                    devices.append(device)
        finally:
            pa.terminate()

        return devices

    def _measure_snr(self, device: MicDevice) -> float:
        """
        Mede SNR do dispositivo.

        Grava por sample_duration segundos, calcula RMS do sinal total
        e estima ruído como o percentil 10 dos frames (silêncio relativo).
        """
        if not HAS_PYAUDIO:
            return -100.0

        pa = pyaudio.PyAudio()
        stream = None
        try:
            # Mono/estéreo: devices "exóticos" (HDMI, roteadores) fazem o
            # PortAudio abortar em C no Linux se abrimos com todos os canais.
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=min(max(device.channels, 1), 2),
                rate=device.sample_rate,
                input=True,
                input_device_index=device.index,
                frames_per_buffer=self._chunk_size,
            )

            frames = []
            num_frames = int(device.sample_rate / self._chunk_size * self._sample_duration)

            for _ in range(num_frames):
                data = stream.read(self._chunk_size, exception_on_overflow=False)
                frames.append(data)

        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            pa.terminate()

        if not frames or np is None:
            return -100.0

        # Converter para numpy array
        audio_data = b"".join(frames)
        samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)

        # Normalizar
        if np.max(np.abs(samples)) > 0:
            samples = samples / 32768.0

        # Calcular RMS por janela (frames de 100ms)
        window_size = int(device.sample_rate * 0.1)
        rms_values = []
        for i in range(0, len(samples), window_size):
            window = samples[i:i + window_size]
            if len(window) > 0:
                rms = np.sqrt(np.mean(window**2))
                if rms > 1e-10:
                    rms_values.append(rms)

        if not rms_values:
            return -100.0

        rms_array = np.array(rms_values)

        # Sinal = RMS médio dos 30% frames mais altos
        signal_rms = np.mean(np.sort(rms_array)[-int(len(rms_array) * 0.3):])
        # Ruído = RMS médio dos 30% frames mais baixos
        noise_rms = np.mean(np.sort(rms_array)[:int(len(rms_array) * 0.3)])

        device.signal_level = float(signal_rms)
        device.noise_level = float(noise_rms)

        if noise_rms <= 1e-10:
            return 60.0  # SNR máximo teórico

        snr = 20.0 * np.log10(signal_rms / max(noise_rms, 1e-10))
        return float(max(-20.0, min(snr, 60.0)))  # Clamp

    def get_device_for_sr(self) -> Optional[int]:
        """Retorna o índice do melhor dispositivo para speech_recognition."""
        with self._lock:
            return self._best_device.index if self._best_device else None

    def get_all_devices(self) -> list[dict[str, Any]]:
        """Retorna todos os dispositivos avaliados para relatório."""
        with self._lock:
            return [
                {
                    "index": d.index,
                    "name": d.name,
                    "channels": d.channels,
                    "sample_rate": d.sample_rate,
                    "snr_db": round(d.snr_db, 1),
                    "signal_level": round(d.signal_level, 4),
                    "noise_level": round(d.noise_level, 4),
                    "is_default": d.is_default,
                    "is_best": d is self._best_device,
                }
                for d in self._devices
            ]