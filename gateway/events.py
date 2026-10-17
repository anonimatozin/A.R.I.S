"""Gateway Event Bus access — singleton for sharing EventBus with HTTP/WebSocket handlers.

O EventBus é opcional: se o core neural não estiver disponível nesta
instalação (ex.: CLL1 com snapshot antigo), get_event_bus() retorna None
e o WebSocket responde 1011 sem derrubar o gateway.
"""

from __future__ import annotations

from typing import Any

_event_bus: Any | None = None
_logger: Any | None = None


def set_event_bus(bus: Any, logger: Any | None = None) -> None:
    """Set the global EventBus instance (called once at startup)."""
    global _event_bus, _logger
    _event_bus = bus
    _logger = logger


def get_event_bus() -> Any | None:
    """Get the global EventBus instance (None se indisponível)."""
    return _event_bus


def get_logger() -> Any | None:
    return _logger
