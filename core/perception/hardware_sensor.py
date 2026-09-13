"""Sensor de hardware do A.R.I.S.

Observa o ``HardwareManager`` (ESP32) já existente e emite eventos de
percepção apenas em transições de conexão (conectou/desconectou) — não
duplica o controle de LEDs nem registra callbacks de botão (já usados
pelo ARIS).
"""

from __future__ import annotations

from typing import Any

from core.neural.events import EVENT_HARDWARE, PRIORITY_HIGH, PRIORITY_NORMAL, Event
from core.perception.sensor import Sensor
from utils.logger import Logger


class HardwareSensor(Sensor):
    """Sensor de estado do hardware ESP32."""

    name = "hardware"

    def __init__(
        self,
        event_bus=None,
        enabled: bool = True,
        interval: float = 8.0,
        logger: Logger | None = None,
        hardware=None,
    ) -> None:
        super().__init__(event_bus=event_bus, enabled=enabled, interval=interval, logger=logger)
        self._hardware = hardware
        self._prev_connected: bool | None = None
        self._prev_available: bool | None = None

    @property
    def available(self) -> bool:
        return self._hardware is not None

    def sense(self) -> list[Event]:
        if not self._enabled or self._hardware is None:
            return []
        connected = bool(self._hardware.connected)
        available = bool(self._hardware.available)

        if self._prev_connected is None:
            self._prev_connected = connected
            self._prev_available = available
            return []

        events: list[Event] = []
        if connected and not self._prev_connected:
            events.append(self._make_event(
                EVENT_HARDWARE,
                {"state": "connected", "available": available,
                 "text": "Hardware ESP32 conectado"},
                priority=PRIORITY_NORMAL, confidence=0.95,
            ))
        elif not connected and self._prev_connected:
            events.append(self._make_event(
                EVENT_HARDWARE,
                {"state": "disconnected", "available": available,
                 "text": "Hardware ESP32 desconectado"},
                priority=PRIORITY_HIGH, confidence=0.95,
            ))

        self._prev_connected = connected
        self._prev_available = available
        return events

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data.update({
            "connected": (self._prev_connected is not None and self._prev_connected),
            "available": (self._prev_available is not None and self._prev_available),
        })
        return data
