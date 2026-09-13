"""Sensor de sistema do A.R.I.S.

Amostra CPU (e, quando psutil existe, RAM e disco). Emite eventos SOMENTE
em mudanças significativas (salto acima do ``delta``) ou em alerta crítico
de CPU. A primeira leitura apenas estabelece a linha de base — nada é
inventado quando a fonte de dados não está disponível.
"""

from __future__ import annotations

from typing import Any

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    HAS_PSUTIL = False

from core.neural.events import (
    EVENT_SYSTEM_ALERT,
    EVENT_SYSTEM_METRIC,
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    Event,
)
from core.perception.sensor import Sensor
from utils.logger import Logger


class SystemSensor(Sensor):
    """Sensor de métricas do sistema (CPU/RAM/disco)."""

    name = "system"

    def __init__(
        self,
        event_bus=None,
        enabled: bool = True,
        interval: float = 15.0,
        logger: Logger | None = None,
        analyzer=None,
        cpu_delta: float = 15.0,
        ram_delta: float = 10.0,
        disk_delta: float = 10.0,
        cpu_critical: float = 90.0,
    ) -> None:
        super().__init__(event_bus=event_bus, enabled=enabled, interval=interval, logger=logger)
        self._analyzer = analyzer
        self._rooms: dict[str, float] = {"cpu": float(cpu_delta)}
        if HAS_PSUTIL:
            self._rooms["ram"] = float(ram_delta)
            self._rooms["disk"] = float(disk_delta)
        self._critical_cpu = float(cpu_critical)
        self._baseline: dict[str, float] = {}
        self._last_snapshot: dict[str, float] = {}
        self._cpu_alert_active = False

    @property
    def available(self) -> bool:
        return HAS_PSUTIL or self._analyzer is not None

    # ── Leitura real ─────────────────────────────────────────

    def _read(self) -> dict[str, float] | None:
        data: dict[str, float] = {}
        if HAS_PSUTIL:
            data["cpu"] = psutil.cpu_percent(interval=None)  # type: ignore[union-attr]
            data["ram"] = psutil.virtual_memory().percent  # type: ignore[union-attr]
            data["disk"] = psutil.disk_usage("/").percent  # type: ignore[union-attr]
            return {k: float(v) for k, v in data.items()}
        if self._analyzer is not None:
            cpu = getattr(self._analyzer, "cpu_usage", None)
            if callable(cpu):
                data["cpu"] = float(cpu())
                return data
        return None

    def get_snapshot(self) -> dict[str, float]:
        """Última amostra lida (para consulta 'estado do sistema')."""
        if not self._last_snapshot:
            data = self._read()
            if data:
                self._last_snapshot = data
        return dict(self._last_snapshot)

    def sense(self) -> list[Event]:
        if not self._enabled:
            return []
        data = self._read()
        if data is None:
            return []
        self._last_snapshot = data
        if not self._baseline:
            self._baseline = data
            return []

        events: list[Event] = []
        prev = self._baseline
        for key, room in self._rooms.items():
            if key not in data or key not in prev:
                continue
            delta = data[key] - prev[key]
            if delta >= room:
                events.append(self._make_event(
                    EVENT_SYSTEM_METRIC,
                    {"metric": key, "value": round(data[key], 1),
                     "delta": round(delta, 1),
                     "text": f"{key.upper()} subiu {delta:.0f}pp para {data[key]:.0f}%"},
                    priority=PRIORITY_HIGH,
                    confidence=0.9,
                ))
        if data.get("cpu", 0) >= self._critical_cpu and not self._cpu_alert_active:
            self._cpu_alert_active = True
            events.append(self._make_event(
                EVENT_SYSTEM_ALERT,
                {"metric": "cpu", "value": round(data["cpu"], 1),
                 "text": f"CPU em {data['cpu']:.0f}% — uso crítico"},
                priority=PRIORITY_CRITICAL,
                confidence=0.95,
            ))
        elif data.get("cpu", 0) < self._critical_cpu - 5 and self._cpu_alert_active:
            self._cpu_alert_active = False

        # Linha de base avança; alertas de delta detectam saltos.
        self._baseline = data
        return events

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data.update({
            "metrics": {
                k: round(v, 1) for k, v in self._last_snapshot.items()
            } if self._last_snapshot else {},
            "cpu_alert_active": self._cpu_alert_active,
        })
        return data
