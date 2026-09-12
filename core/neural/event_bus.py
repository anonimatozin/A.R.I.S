"""Event Bus do A.R.I.S.

Publica, assina, processa e controla erros de eventos. Permite que
módulos se comuniquem sem conhecer uns aos outros: cada consumidor
assina apenas os tipos de evento que lhe interessam.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from core.neural.events import Event
from utils.logger import Logger

EventHandler = Callable[[Event], Any]


class EventBus:
    """Barramento central de eventos.

    - ``subscribe(event_type, handler)``: assina um handler.
    - ``publish(event)``: entrega o evento aos assinantes.
    - ``process(event)``: alias de ``publish`` (processamento síncrono).

    Erros dentro de um handler nunca derrubam o barramento: são
    capturados, contados e logados.
    """

    def __init__(self, logger: Logger | None = None) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._wildcard: list[EventHandler] = []
        self._logger = logger
        self._delivered = 0
        self._published = 0
        self._errors = 0

    # ── Assinatura ───────────────────────────────────────────

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Assina um handler para um tipo de evento."""
        if event_type == "*":
            if handler not in self._wildcard:
                self._wildcard.append(handler)
        else:
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        """Remove uma assinatura."""
        if event_type == "*":
            try:
                self._wildcard.remove(handler)
                return True
            except ValueError:
                return False
        try:
            self._subscribers[event_type].remove(handler)
            return True
        except ValueError:
            return False

    def subscriber_count(self, event_type: str | None = None) -> int:
        """Quantidade de assinantes (de um tipo, ou total)."""
        if event_type is not None:
            return len(self._subscribers.get(event_type, []))
        return sum(len(v) for v in self._subscribers.values()) + len(self._wildcard)

    # ── Publicação ───────────────────────────────────────────

    def publish(self, event: Event) -> int:
        """Publica um evento para todos os assinantes.

        Returns:
            Número de handlers que processaram o evento com sucesso.
        """
        self._published += 1
        handlers = list(self._wildcard) + list(self._subscribers.get(event.event_type, []))
        delivered = 0
        for handler in handlers:
            try:
                handler(event)
                delivered += 1
            except Exception as e:
                self._errors += 1
                if self._logger:
                    self._logger.error(
                        f"EventBus: handler {getattr(handler, '__name__', handler)} "
                        f"falhou para {event.event_type}: {e}"
                    )
        self._delivered += delivered
        return delivered

    def process(self, event: Event) -> int:
        """Processa um evento (alias síncrono de ``publish``)."""
        return self.publish(event)

    # ── Estatísticas ─────────────────────────────────────────

    def get_stats(self) -> dict[str, int]:
        """Estatísticas de uso do barramento."""
        return {
            "published": self._published,
            "delivered": self._delivered,
            "errors": self._errors,
            "subscribers": self.subscriber_count(),
        }
