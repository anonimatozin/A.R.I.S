"""Configuração central da camada de percepção do A.R.I.S.

Todo o comportamento dos sensores é controlado por variáveis de
ambiente (prefixo ``ARIS_``) com defaults que NÃO exigem câmera,
microfone ou internet para o sistema operar: sensores indisponíveis
ficam ``offline`` e emitir zero eventos (nunca dados falsos).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PerceptionConfig:
    """Configuração da camada de percepção.

    Attributes:
        enabled: Liga/desliga a camada como um todo.
        camera_enabled: Câmera (default False — sem câmera exigida).
        camera_interval: Intervalo de captura (s).
        camera_motion_threshold: Fração mínima de mudança p/ movimento.
        camera_object_interval: Intervalo mínimo entre detecções de objetos.
        mic_enabled: Microfone (default False — reutiliza eventos de voz).
        mic_relay: Reemite eventos de voz como percepção (evita duplicar STT).
        screen_enabled: Observação de tela (janela ativa).
        screen_ocr_enabled: OCR de tela (pesado; default off).
        screen_ocr_interval: Intervalo mínimo entre OCRs (s).
        system_enabled: Métricas de sistema (CPU/RAM/disco).
        system_interval: Intervalo de amostragem (s).
        system_cpu_delta: Salto em pp que dispara evento (CPU).
        system_ram_delta: Salto em pp que dispara evento (RAM).
        system_disk_delta: Salto em pp que dispara evento (disco).
        system_cpu_critical: Limiar de alerta de CPU (%).
        filesystem_watch_dirs: Diretórios vigiados (separador ';').
        filesystem_interval: Intervalo de varredura (s).
        network_enabled: Verificação de internet.
        network_interval: Intervalo entre verificações (s).
        network_timeout: Timeout de conexão (s).
        hardware_enabled: Sensor do HardwareManager (ESP32).
        hardware_interval: Intervalo de sincronização (s).
    """

    enabled: bool = True
    camera_enabled: bool = False
    camera_interval: float = 2.0
    camera_motion_threshold: float = 0.04
    camera_object_interval: float = 30.0
    mic_enabled: bool = False
    mic_relay: bool = False
    screen_enabled: bool = True
    screen_ocr_enabled: bool = False
    screen_ocr_interval: float = 120.0
    system_enabled: bool = True
    system_interval: float = 15.0
    system_cpu_delta: float = 15.0
    system_ram_delta: float = 10.0
    system_disk_delta: float = 10.0
    system_cpu_critical: float = 90.0
    filesystem_watch_dirs: tuple[str, ...] = ()
    filesystem_interval: float = 10.0
    network_enabled: bool = True
    network_interval: float = 30.0
    network_timeout: float = 3.0
    hardware_enabled: bool = True
    hardware_interval: float = 8.0

    # Voz contínua (novo)
    continuous_voice_enabled: bool = False
    continuous_voice_wake_words: tuple[str, ...] = ("aris", "arís", "ariz", "arizs")
    continuous_voice_vad_aggressiveness: int = 2
    continuous_voice_sample_rate: int = 16000
    continuous_voice_frame_duration_ms: int = 30
    continuous_voice_silence_timeout_ms: int = 1200
    continuous_voice_min_speech_ms: int = 300
    continuous_voice_max_speech_ms: int = 30000
    continuous_voice_stt_model: str = "tiny"
    continuous_voice_stt_device: str = "cpu"
    continuous_voice_stt_compute_type: str = "int8"
    continuous_voice_vosk_model_path: str = "vosk-model-pt"
    continuous_voice_language: str = "pt"
    continuous_voice_min_confidence: float = 0.35
    continuous_voice_cooldown_ms: int = 1000

    @classmethod
    def load(cls) -> PerceptionConfig:
        """Carrega a configuração a partir do ambiente."""
        dirs = tuple(
            d.strip()
            for d in os.getenv("ARIS_FILESYSTEM_WATCH_DIRS", "").split(";")
            if d.strip()
        )
        return cls(
            enabled=_env_bool("ARIS_PERCEPTION_ENABLED", True),
            camera_enabled=_env_bool("ARIS_CAMERA_ENABLED", False),
            camera_interval=_env_float("ARIS_CAMERA_INTERVAL", 2.0),
            camera_motion_threshold=_env_float("ARIS_CAMERA_MOTION_THRESHOLD", 0.04),
            camera_object_interval=_env_float("ARIS_CAMERA_OBJECT_INTERVAL", 30.0),
            mic_enabled=_env_bool("ARIS_MIC_ENABLED", False),
            mic_relay=_env_bool("ARIS_MIC_RELAY", False),
            screen_enabled=_env_bool("ARIS_SCREEN_ENABLED", True),
            screen_ocr_enabled=_env_bool("ARIS_SCREEN_OCR_ENABLED", False),
            screen_ocr_interval=_env_float("ARIS_SCREEN_OCR_INTERVAL", 120.0),
            system_enabled=_env_bool("ARIS_SYSTEM_ENABLED", True),
            system_interval=_env_float("ARIS_SYSTEM_INTERVAL", 15.0),
            system_cpu_delta=_env_float("ARIS_SYSTEM_CPU_DELTA", 15.0),
            system_ram_delta=_env_float("ARIS_SYSTEM_RAM_DELTA", 10.0),
            system_disk_delta=_env_float("ARIS_SYSTEM_DISK_DELTA", 10.0),
            system_cpu_critical=_env_float("ARIS_SYSTEM_CPU_CRITICAL", 90.0),
            filesystem_watch_dirs=dirs,
            filesystem_interval=_env_float("ARIS_FILESYSTEM_INTERVAL", 10.0),
            network_enabled=_env_bool("ARIS_NETWORK_ENABLED", True),
            network_interval=_env_float("ARIS_NETWORK_INTERVAL", 30.0),
            network_timeout=_env_float("ARIS_NETWORK_TIMEOUT", 3.0),
            hardware_enabled=_env_bool("ARIS_HARDWARE_ENABLED", True),
            hardware_interval=_env_float("ARIS_HARDWARE_INTERVAL", 8.0),
            continuous_voice_enabled=_env_bool("ARIS_CONTINUOUS_VOICE_ENABLED", False),
            continuous_voice_wake_words=tuple(
                w.strip() for w in os.getenv("ARIS_CONTINUOUS_VOICE_WAKE_WORDS", "aris,arís,ariz,arizs").split(",") if w.strip()
            ),
            continuous_voice_vad_aggressiveness=_env_int("ARIS_CONTINUOUS_VOICE_VAD_AGGRESSIVENESS", 2),
            continuous_voice_sample_rate=_env_int("ARIS_CONTINUOUS_VOICE_SAMPLE_RATE", 16000),
            continuous_voice_frame_duration_ms=_env_int("ARIS_CONTINUOUS_VOICE_FRAME_DURATION_MS", 30),
            continuous_voice_silence_timeout_ms=_env_int("ARIS_CONTINUOUS_VOICE_SILENCE_TIMEOUT_MS", 1200),
            continuous_voice_min_speech_ms=_env_int("ARIS_CONTINUOUS_VOICE_MIN_SPEECH_MS", 300),
            continuous_voice_max_speech_ms=_env_int("ARIS_CONTINUOUS_VOICE_MAX_SPEECH_MS", 30000),
            continuous_voice_stt_model=os.getenv("ARIS_CONTINUOUS_VOICE_STT_MODEL", "tiny"),
            continuous_voice_stt_device=os.getenv("ARIS_CONTINUOUS_VOICE_STT_DEVICE", "cpu"),
            continuous_voice_stt_compute_type=os.getenv("ARIS_CONTINUOUS_VOICE_STT_COMPUTE_TYPE", "int8"),
            continuous_voice_vosk_model_path=os.getenv("ARIS_CONTINUOUS_VOICE_VOSK_MODEL_PATH", "vosk-model-pt"),
            continuous_voice_language=os.getenv("ARIS_CONTINUOUS_VOICE_LANGUAGE", "pt"),
            continuous_voice_min_confidence=_env_float("ARIS_CONTINUOUS_VOICE_MIN_CONFIDENCE", 0.35),
            continuous_voice_cooldown_ms=_env_int("ARIS_CONTINUOUS_VOICE_COOLDOWN_MS", 1000),
        )

    def update_env(self, **overrides: object) -> PerceptionConfig:
        """Nova configuração com os campos fornecidos sobrescritos."""
        data = {
            f.name: getattr(self, f.name)
            for f in self.__dataclass_fields__.values()
        }
        data.update(overrides)
        return self.__class__(**data)
