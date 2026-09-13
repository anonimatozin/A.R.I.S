"""Sensor de rede do A.R.I.S.

Verifica conectividade por socket (sem dependências externas) e emite
eventos APENAS em transições de estado (perda/recuperação de internet).
Estado estável não gera ruído.
"""

from __future__ import annotations

import socket
import time
from typing import Any

from core.neural.events import EVENT_NETWORK, PRIORITY_HIGH, PRIORITY_NORMAL, Event
from core.perception.sensor import Sensor
from utils.logger import Logger


class NetworkSensor(Sensor):
    """Sensor de disponibilidade de internet."""

    name = "network"

    def __init__(
        self,
        event_bus=None,
        enabled: bool = True,
        interval: float = 30.0,
        logger: Logger | None = None,
        hosts: tuple[str, ...] = ("8.8.8.8", "1.1.1.1"),
        port: int = 53,
        timeout: float = 3.0,
    ) -> None:
        super().__init__(event_bus=event_bus, enabled=enabled, interval=interval, logger=logger)
        self._hosts = tuple(hosts)
        self._port = int(port)
        self._timeout = float(timeout)
        self._reachable: bool | None = None
        self._latency_ms: float = 0.0

    @property
    def available(self) -> bool:
        return True

    # ── Verificação real ─────────────────────────────────────

    def _probe(self) -> bool:
        for host in self._hosts:
            try:
                start = time.monotonic()
                with socket.create_connection((host, self._port), timeout=self._timeout):
                    self._latency_ms = round((time.monotonic() - start) * 1000, 1)
                return True
            except OSError:
                continue
        return False

    def sense(self) -> list[Event]:
        if not self._enabled:
            return []
        reachable = self._probe()
        if self._reachable is None:
            self._reachable = reachable
            return []

        events: list[Event] = []
        if reachable and not self._reachable:
            events.append(self._make_event(
                EVENT_NETWORK,
                {"state": "up", "latency_ms": self._latency_ms,
                 "text": "Internet restaurada"},
                priority=PRIORITY_NORMAL, confidence=0.9,
            ))
        elif not reachable and self._reachable:
            events.append(self._make_event(
                EVENT_NETWORK,
                {"state": "down",
                 "text": "Conexão com a internet perdida"},
                priority=PRIORITY_HIGH, confidence=0.9,
            ))
        self._reachable = reachable
        return events

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data.update({
            "reachable": self._reachable,
            "latency_ms": self._latency_ms,
        })
        return data
