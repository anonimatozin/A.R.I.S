"""Memória de trabalho (Working Memory) do A.R.I.S.

Memória temporária e volátil para a tarefa em curso: objetivo,
intenção, entidades, parâmetros, ações executadas, resultados e estado
da tarefa. Distinta da memória persistente de longo prazo.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TaskState:
    """Estado atômico de uma tarefa na memória de trabalho."""
    goal: str = ""
    intent: str = ""
    entities: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    status: str = "pending"  # pending | running | success | failed
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serializa o estado da tarefa."""
        return {
            "goal": self.goal,
            "intent": self.intent,
            "entities": dict(self.entities),
            "params": self.params,
            "actions": list(self.actions),
            "results": list(self.results),
            "status": self.status,
            "started_at": self.started_at,
        }


class WorkingMemory:
    """Memória de trabalho do sistema.

    Guarda o estado da tarefa corrente e um histórico limitado de
    tarefas anteriores.
    """

    def __init__(self, maxlen: int = 20) -> None:
        self._current = TaskState()
        self._history: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._notes: dict[str, Any] = {}

    # ── Tarefa corrente ──────────────────────────────────────

    def start_task(self, goal: str, intent: str = "") -> TaskState:
        """Arquiva a tarefa anterior e inicia uma nova."""
        self._archive_current()
        self._current = TaskState(goal=goal, intent=intent)
        return self._current

    def update_task(self, **kwargs: Any) -> None:
        """Atualiza campos da tarefa corrente."""
        for key, value in kwargs.items():
            if key == "entities":
                self._current.entities.update(value or {})
            elif key == "params":
                self._current.params.update(value or {})
            elif key == "status":
                self._current.status = value
            elif hasattr(TaskState, key):
                setattr(self._current, key, value)

    def set_status(self, status: str) -> None:
        """Define o status da tarefa corrente."""
        self._current.status = status

    def add_action(self, action: str) -> None:
        """Registra uma ação executada na tarefa."""
        self._current.actions.append(action)

    def add_result(self, result: dict[str, Any]) -> None:
        """Registra o resultado de uma ação."""
        self._current.results.append(result)

    def add_entity(self, name: str, value: str) -> None:
        """Registra uma entidade relevante."""
        self._current.entities[name] = value

    def complete_current_task(self, result: str = "", success: bool = True) -> None:
        """Registra o desfecho da tarefa corrente."""
        self._current.status = "success" if success else "failed"
        self._current.results.append({"result": result, "success": success})

    def reflect_result(self, result: str = "", success: bool = True) -> None:
        """Registra um resultado/reflexão e atualiza o status."""
        self._current.results.append({"result": result, "success": success})
        self._current.status = "success" if success else "failed"

    def current(self) -> TaskState:
        """Retorna o estado da tarefa corrente."""
        return self._current

    def snapshot(self) -> dict[str, Any]:
        """Snapshot da tarefa corrente."""
        return self._current.to_dict()

    def remember(self, key: str, value: Any) -> None:
        """Anota um valor de interesse geral (notas da sessão)."""
        self._notes[key] = value

    def recall(self, key: str, default: Any = None) -> Any:
        """Recupera uma anotação da sessão."""
        return self._notes.get(key, default)

    # ── Histórico ────────────────────────────────────────────

    def _archive_current(self) -> None:
        if self._current.goal or self._current.actions:
            self._history.append(self._current.to_dict())

    def history(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Histórico de tarefas anteriores (mais recentes primeiro)."""
        items = list(self._history)[::-1]
        return items[:limit] if limit else items

    def clear(self) -> None:
        """Limpa a memória de trabalho."""
        self._archive_current()
        self._current = TaskState()
        self._notes.clear()

    def __len__(self) -> int:
        return len(self._history)

    def __repr__(self) -> str:
        return f"WorkingMemory(task={self._current.goal!r}, status={self._current.status})"
