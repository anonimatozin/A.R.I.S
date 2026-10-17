"""Estado da tarefa em andamento + emissão segura de eventos (redação de segredos)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from ..contract.types import AgentEvent, EventSink
from ..contract.utils import redact_secrets
from .plan import PlanState

log = logging.getLogger("aris.agent.core.state")


def redigir(obj: object) -> object:
    """Aplica ``redact_secrets`` em toda string de uma estrutura JSON-friendly."""
    if isinstance(obj, str):
        return redact_secrets(obj)
    if isinstance(obj, dict):
        return {key: redigir(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redigir(value) for value in obj]
    return obj


class Emitter:
    """Manda eventos para a UI sem deixar segredo vazar nem exceção escapar."""

    def __init__(self, sink: EventSink | None = None) -> None:
        self._sink = sink

    def emit(self, tipo: str, data: dict) -> None:
        if self._sink is None:
            return
        evento = AgentEvent(type=tipo, data=redigir(dict(data)))  # type: ignore[arg-type]
        try:
            self._sink(evento)
        except Exception:  # noqa: BLE001 - UI não pode derrubar o laço
            log.warning("sink de eventos falhou em %s", tipo, exc_info=True)


@dataclass
class TaskState:
    """O que vive durante uma tarefa de uma sessão (uma por ``run``)."""

    session_id: str
    trace_id: str
    cancel: threading.Event  # setado = abortar o mais rápido possível
    plan: PlanState
    emitter: Emitter
    active: bool = True

    def emit(self, tipo: str, data: dict) -> None:
        self.emitter.emit(tipo, data)


__all__ = ["Emitter", "TaskState", "redigir"]
