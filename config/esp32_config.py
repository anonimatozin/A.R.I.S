"""Configuração do ESP32 para A.R.I.S.

Configuração centralizada para comunicação e hardware.
Tudo vem de env vars para não ter GPIOs no código.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ESP32Config:
    """Configuração do ESP32."""

    # Conexão
    enabled: bool = field(default_factory=lambda: os.getenv("ESP32_ENABLED", "true").lower() == "true")
    connection_type: str = field(default_factory=lambda: os.getenv("ESP32_CONNECTION", "websocket"))
    ws_host: str = field(default_factory=lambda: os.getenv("ESP32_WS_HOST", "127.0.0.1"))
    ws_port: int = field(default_factory=lambda: int(os.getenv("ESP32_WS_PORT", "8766")))
    esp32_ip: str = field(default_factory=lambda: os.getenv("ESP32_IP", ""))

    # Heartbeat
    heartbeat_interval: float = field(default_factory=lambda: float(os.getenv("ESP32_HEARTBEAT", "5.0")))
    heartbeat_timeout: float = field(default_factory=lambda: float(os.getenv("ESP32_TIMEOUT", "15.0")))

    # Reconexão
    reconnect_delay: float = field(default_factory=lambda: float(os.getenv("ESP32_RECONNECT_DELAY", "3.0")))
    max_reconnect_attempts: int = field(default_factory=lambda: int(os.getenv("ESP32_MAX_RECONNECT", "10")))

    # Simulação (para desenvolvimento sem hardware)
    simulation: bool = field(default_factory=lambda: os.getenv("HARDWARE_SIMULATION", "false").lower() == "true")

    # Botão - ações configuráveis
    button_single_click: str = field(default_factory=lambda: os.getenv("ESP32_BTN_1", "voice_toggle"))
    button_double_click: str = field(default_factory=lambda: os.getenv("ESP32_BTN_2", "stop_speaking"))
    button_triple_click: str = field(default_factory=lambda: os.getenv("ESP32_BTN_3", "turbo_mode"))
    button_quad_click: str = field(default_factory=lambda: os.getenv("ESP32_BTN_4", "config_action"))
    button_long_press: str = field(default_factory=lambda: os.getenv("ESP32_BTN_LONG", "reconnect"))

    # LEDs - brilho padrão
    default_brightness: int = field(default_factory=lambda: int(os.getenv("ESP32_BRIGHTNESS", "80")))

    # Log
    log_prefix: str = "[HARDWARE]"
