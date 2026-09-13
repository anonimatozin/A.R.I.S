"""Base abstrata de sensores da percepção do A.R.I.S.

Cada sensor lê uma fonte do mundo real e devolve ``Event``s estruturados
apenas quando há algo *notável*: mudança de estado, transição ou valor
acima de limiar. Sensores indisponíveis retornam ``[]`` e ficam
``offline`` — nunca dados falsos.

O ciclo de vida centraliza o threading: a lógica de leitura fica em
``sense()`` (puro, testável) e a base cuida do loop + publicação.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from core.neural.event_bus import EventBus
from core.neural.events import EVENT_PERCEPTION, PRIORITY_NORMAL, Event
from utils.logger import Logger

# Status canônicos de um sensor
STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_OFFLINE = "offline"
STATUS_DISABLED = "disabled"
STATUS_ERROR = "error"


class Sensor(ABC):
    """Construtor base de sensores.

    Attributes:
        name: Identificação do sensor (ex.: ``camera``).
        event_bus: Event Bus para publicação dos eventos.
        enabled: Se o sensor está ativo.
        interval: Intervalo (s) entre leituras.
    """

    name: str = "sensor"

    def __init__(
        self,
        event_bus: EventBus | None = None,
        enabled: bool = True,
        interval: float = 10.0,
        logger: Logger | None = None,
    ) -> None:
        self.event_bus = event_bus
        self._enabled = bool(enabled)
        self._interval = max(0.5, float(interval))
        self._logger = logger
        self._status = STATUS_IDLE
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_event_at: float | None = None
        self._events_emitted = 0
        self._last_error = ""

    # ── Estado ───────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """Indica se a fonte do sensor está acessível neste ambiente."""
        return True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def status(self) -> str:
        return self._status

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def last_error(self) -> str:
        return self._last_error

    def set_enabled(self, enabled: bool) -> None:
        """Habilita/desabilita o sensor (não afeta threads já ativas)."""
        self._enabled = bool(enabled)
        if not self._enabled and self._status == STATUS_RUNNING:
            self._status = STATUS_IDLE

    # ── Leitura (implementação do sensor) ────────────────────

    @abstractmethod
    def sense(self) -> list[Event]:
        """Lê o mundo e devolve os eventos notáveis (ou ``[]``).

        Nunca deve bloquear por muito tempo; sem novas informações,
        retorna lista vazia.
        """

    # ── Publicação ───────────────────────────────────────────

    def _make_event(
        self,
        event_type: str = EVENT_PERCEPTION,
        payload: dict[str, Any] | None = None,
        priority: int = PRIORITY_NORMAL,
        confidence: float = 1.0,
    ) -> Event:
        return Event(
            event_type=event_type,
            source=self.name,
            payload=payload or {},
            confidence=confidence,
            priority=priority,
        )

    def _publish(self, events: list[Event]) -> int:
        for event in events:
            self._last_event_at = time.time()
            self._events_emitted += 1
            if self.event_bus is not None:
                self.event_bus.publish(event)
        return len(events)

    # ── Ciclo de vida ────────────────────────────────────────

    def start(self) -> None:
        """Inicia o loop de leitura em thread própria (daemon)."""
        if self._thread is not None and self._thread.is_alive():
            return
        if not self._enabled:
            self._status = STATUS_DISABLED
            return
        if not self.available:
            self._status = STATUS_OFFLINE
            return
        self._stop_event.clear()
        self._status = STATUS_RUNNING
        self._thread = threading.Thread(
            target=self._loop,
            name=f"perception.{self.name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Para o loop e aguarda o término da thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._status == STATUS_RUNNING:
            self._status = STATUS_IDLE

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._publish(self.sense())
            except Exception as e:
                self._status = STATUS_ERROR
                self._last_error = str(e)
                if self._logger:
                    self._logger.error(f"Sensor {self.name}: {e}")
            self._stop_event.wait(self._interval)

    def run_once(self) -> list[Event]:
        """Leitura única (usada por testes e comandos manuais)."""
        events = self.sense()
        self._publish(events)
        return events

    # ── Relatório ────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Estado resumido do sensor."""
        return {
            "name": self.name,
            "enabled": self._enabled,
            "status": self._status,
            "available": self.available,
            "interval": self._interval,
            "last_event_at": (
                time.strftime("%H:%M:%S", time.localtime(self._last_event_at))
                if self._last_event_at else None
            ),
            "events_emitted": self._events_emitted,
            "last_error": self._last_error,
        }
