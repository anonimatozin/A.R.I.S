"""Perception Manager do A.R.I.S.

Orquestra os sensores e a ponte de atenção. Construção única:
``PerceptionManager.with_defaults(...)`` monta os 7 sensores a partir
da configuração e dos provedores existentes (awareness, hardware,
analyzer). ``start()``/``stop()`` controlam o ciclo de vida; o resto é
consulta amigável (status, sensores, atenção, câmera) para handlers.
"""

from __future__ import annotations

from typing import Any

from core.neural.attention.attention_engine import AttentionEngine
from core.neural.event_bus import EventBus
from core.neural.memory.system import MemorySystem
from core.neural.state import GlobalState
from core.perception.attention_bridge import AttentionBridge
from core.perception.camera_sensor import CameraSensor
from core.perception.config import PerceptionConfig
from core.perception.filesystem_sensor import FilesystemSensor
from core.perception.hardware_sensor import HardwareSensor
from core.perception.microphone_sensor import MicrophoneSensor
from core.perception.network_sensor import NetworkSensor
from core.perception.screen_sensor import ScreenSensor
from core.perception.sensor import Sensor
from core.perception.system_sensor import SystemSensor
from utils.logger import Logger

# Nomes amigáveis e rótulos de status em PT-BR.
SENSOR_LABELS = {
    "camera": "Câmera",
    "microphone": "Microfone",
    "screen": "Tela",
    "system": "Sistema",
    "filesystem": "Arquivos",
    "network": "Rede",
    "hardware": "Hardware ESP32",
}

STATUS_LABELS = {
    "running": "ativo",
    "idle": "inativo",
    "disabled": "desativado",
    "offline": "indisponível",
    "error": "erro",
}


class PerceptionManager:
    """Camada de percepção: sensores + atenção integrados ao Neural Core."""

    def __init__(
        self,
        event_bus: EventBus,
        state: GlobalState | None = None,
        attention: AttentionEngine | None = None,
        memory: MemorySystem | None = None,
        config: PerceptionConfig | None = None,
        logger: Logger | None = None,
        sensors: dict[str, Sensor] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._state = state
        self._attention = attention
        self._memory = memory
        self._config = config or PerceptionConfig.load()
        self._logger = logger
        self._intended: dict[str, bool] = {}
        self.sensors: dict[str, Sensor] = sensors or {}
        for name, sensor in self.sensors.items():
            self._intended[name] = sensor.enabled
        if attention is None:
            attention = AttentionEngine(logger=logger)
        self._bridge = AttentionBridge(
            event_bus=event_bus,
            attention=attention,
            state=state,
            memory=memory,
            logger=logger,
        )
        self._started = False

    # ── Fábrica ──────────────────────────────────────────────

    @classmethod
    def with_defaults(
        cls,
        event_bus: EventBus,
        state: GlobalState | None = None,
        attention: AttentionEngine | None = None,
        memory: MemorySystem | None = None,
        config: PerceptionConfig | None = None,
        logger: Logger | None = None,
        awareness=None,
        hardware=None,
        analyzer=None,
    ) -> PerceptionManager:
        """Constrói o manager com os 7 sensores a partir do mundo real."""
        cfg = config or PerceptionConfig.load()
        sensors: dict[str, Sensor] = {
            "camera": CameraSensor(
                event_bus, enabled=cfg.camera_enabled, interval=cfg.camera_interval,
                logger=logger, motion_threshold=cfg.camera_motion_threshold,
                object_interval=cfg.camera_object_interval,
            ),
            "microphone": MicrophoneSensor(
                event_bus, enabled=cfg.mic_enabled, logger=logger, relay=cfg.mic_relay),
            "screen": ScreenSensor(
                event_bus, enabled=cfg.screen_enabled, logger=logger,
                awareness=awareness, ocr_enabled=cfg.screen_ocr_enabled,
                ocr_interval=cfg.screen_ocr_interval,
            ),
            "system": SystemSensor(
                event_bus, enabled=cfg.system_enabled, interval=cfg.system_interval,
                logger=logger, analyzer=analyzer, cpu_delta=cfg.system_cpu_delta,
                ram_delta=cfg.system_ram_delta, disk_delta=cfg.system_disk_delta,
                cpu_critical=cfg.system_cpu_critical,
            ),
            "filesystem": FilesystemSensor(
                event_bus, enabled=bool(cfg.filesystem_watch_dirs),
                interval=cfg.filesystem_interval, logger=logger,
                watch_dirs=cfg.filesystem_watch_dirs,
            ),
            "network": NetworkSensor(
                event_bus, enabled=cfg.network_enabled, interval=cfg.network_interval,
                logger=logger, timeout=cfg.network_timeout,
            ),
            "hardware": HardwareSensor(
                event_bus, enabled=cfg.hardware_enabled, interval=cfg.hardware_interval,
                logger=logger, hardware=hardware,
            ),
        }
        return cls(
            event_bus=event_bus, state=state, attention=attention, memory=memory,
            config=cfg, logger=logger, sensors=sensors,
        )

    # ── Ciclo de vida ────────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        return self._started

    def start(self) -> None:
        """Inicia os sensores habilitados e a ponte de atenção."""
        cfg_enabled = self._config.enabled
        for sensor in self.sensors.values():
            sensor.set_enabled(sensor.enabled and cfg_enabled)
            sensor.start()
        self._bridge.set_enabled(cfg_enabled)
        self._started = cfg_enabled
        self._sync_state()
        if self._logger:
            active = sum(1 for s in self.sensors.values() if s.status == "running")
            self._logger.info(
                f"Percepção: {'ativa' if self._started else 'desativada'} "
                f"({active}/{len(self.sensors)} sensores ativos)"
            )

    def stop(self) -> None:
        """Para todos os sensores e a ponte de atenção."""
        for sensor in self.sensors.values():
            sensor.stop()
        self._bridge.set_enabled(False)
        self._started = False
        self._sync_state()

    def toggle_perception(self, on: bool | None = None) -> bool:
        """Liga/desliga a percepção inteira (master switch)."""
        target = self.is_enabled if on is None else bool(on)
        if target == self.is_enabled:
            return self.is_enabled
        if target:
            for name, sensor in self.sensors.items():
                sensor.set_enabled(self._intended.get(name, True))
                sensor.start()
            self._bridge.set_enabled(True)
            self._started = True
        else:
            self.stop()
        self._sync_state()
        return self.is_enabled

    # ── Sensores ─────────────────────────────────────────────

    def sensor(self, name: str) -> Sensor | None:
        return self.sensors.get(name)

    def set_sensor_enabled(self, name: str, enabled: bool) -> bool:
        sensor = self.sensors.get(name)
        if sensor is None:
            return False
        sensor.set_enabled(bool(enabled))
        self._intended[name] = bool(enabled)
        self._sync_state()
        return True

    # ── Estado global ────────────────────────────────────────

    def _sync_state(self) -> None:
        if self._state is None:
            return
        statuses = {name: s.status for name, s in self.sensors.items()}
        active = sum(1 for s in self.sensors.values() if s.status == "running")
        self._state.update_perception(
            enabled=self._started,
            active_sensors=active,
            sensors=statuses,
        )

    # ── Consultas amigáveis ──────────────────────────────────

    def get_status(self) -> dict[str, dict[str, Any]]:
        return {name: sensor.snapshot() for name, sensor in self.sensors.items()}

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self._started,
            "active_sensors": sum(1 for s in self.sensors.values() if s.status == "running"),
            "sensors": self.get_status(),
            "attention": self._bridge.get_stats(),
        }

    def describe(self) -> str:
        """Resumo para a pergunta 'o que você está percebendo?'."""
        if not self._started:
            return "Percepção desativada. Diga 'ative a percepção' para ligar."
        active = [n for n, s in self.sensors.items() if s.status == "running"]
        parts = [
            f"Percepção ativa com {len(active)} sensores: "
            f"{', '.join(SENSOR_LABELS.get(n, n) for n in active) or 'nenhum'}."
        ]
        system = self.sensor("system")
        if system is not None and system.status == "running" and hasattr(system, "get_snapshot"):
            metrics = system.get_snapshot()
            if metrics:
                parts.append("Sistema: " + " | ".join(
                    f"{name}={value:.0f}%" for name, value in metrics.items()))
        network = self.sensor("network")
        if network is not None and network.status == "running":
            net_snap = network.snapshot()
            if net_snap.get("reachable") is not None:
                state_text = "conectada" if net_snap["reachable"] else "indisponível"
                parts.append(f"Internet: {state_text}")
        if self._state is not None:
            parts.append(
                f"Atenção atual: {self._state.perception.last_attention}"
                + (f" — {self._state.perception.attention_focus}" if self._state.perception.attention_focus else "")
            )
        return " ".join(parts)

    def format_sensors(self) -> str:
        """Tabela de sensores para 'quais sensores estão ativos?'."""
        lines = []
        for name, sensor in self.sensors.items():
            status = STATUS_LABELS.get(sensor.status, sensor.status)
            extra = ""
            if sensor.status == "offline":
                extra = " (sem suporte neste ambiente)"
            lines.append(f"  • {SENSOR_LABELS.get(name, name)}: {status}{extra}")
        return "\n".join(lines)

    def format_attention(self) -> str:
        """O que chamou a atenção recentemente."""
        recent = self._attention.recent_attention(10) if self._attention else []
        if not recent:
            return "Nenhum evento relevante registrado ainda."
        lines = []
        for entry in recent:
            lines.append(
                f"  • [{entry['level']}] {entry['event_type']} "
                f"(score {entry['score']:.2f}) — {entry['text'] or entry['source']}"
            )
        return "\n".join(lines)

    def format_camera(self) -> str:
        """Status da câmera (pergunta direta)."""
        camera = self.sensors.get("camera")
        if camera is None:
            return "Sensor de câmera não configurado."
        if not camera.available:
            return "Câmera indisponível (OpenCV ou dispositivo não encontrado)."
        if camera.status == "running":
            snap = camera.snapshot()
            return (
                f"Câmera ativa (frames: {snap['exposures']}, "
                f"movimento: {'sim' if snap['motion_active'] else 'não'}, "
                f"pessoas detectadas: {snap['humans_detected']})."
            )
        return f"Câmera disponível, porém {STATUS_LABELS.get(camera.status, camera.status)}."
