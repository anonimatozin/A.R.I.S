"""Context Engine do A.R.I.S.

Constrói o contexto relevante para cada tarefa combinando:

    user input
    + task atual (working memory)
    + eventos recentes
    + estado do sistema
    + memória de trabalho
    + memória de longo prazo RELEVANTE (selecionada)

Nunca envia toda a memória para o LLM: apenas memórias relevantes
(por relevância de busca e importância) são incluídas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.neural.events import Event
from core.neural.memory.system import MemorySystem
from core.neural.memory.working_memory import WorkingMemory
from core.neural.state import GlobalState
from utils.logger import Logger


@dataclass
class ContextBundle:
    """Contexto montado para uma tarefa."""
    user_input: str = ""
    current_task: dict[str, Any] = field(default_factory=dict)
    current_goal: str = ""
    current_mode: str = ""
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    system_snapshot: dict[str, Any] = field(default_factory=dict)
    long_term_memories: list[dict[str, Any]] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_input": self.user_input,
            "current_task": self.current_task,
            "current_goal": self.current_goal,
            "current_mode": self.current_mode,
            "recent_events": self.recent_events,
            "system_snapshot": self.system_snapshot,
            "long_term_memories": self.long_term_memories,
            "notes": self.notes,
        }

    def estimate_tokens(self) -> int:
        """Estimativa grosseira de tokens do contexto."""
        text = self.to_prompt_str()
        return max(1, len(text) // 4)

    def to_prompt_str(self, max_chars: int = 4000) -> str:
        """Formata o contexto para uso em prompts, limitado."""
        parts: list[str] = []
        if self.user_input:
            parts.append(f"Entrada do operador: {self.user_input}")
        if self.current_goal:
            parts.append(f"Objetivo atual: {self.current_goal}")
        if self.current_mode:
            parts.append(f"Modo atual: {self.current_mode}")
        if self.current_task and self.current_task.get("intent"):
            parts.append(f"Intenção em curso: {self.current_task['intent']}")
        if self.recent_events:
            events = " | ".join(
                f"{e['type']}({e['source']})" for e in self.recent_events[-5:]
            )
            parts.append(f"Eventos recentes: {events}")
        if self.notes:
            notes = ", ".join(f"{k}={v}" for k, v in self.notes.items())
            parts.append(f"Notas: {notes}")
        if self.long_term_memories:
            parts.append("Memórias relevantes:")
            for m in self.long_term_memories[:5]:
                parts.append(f"  - {m.get('title', '')}: {str(m.get('content', ''))[:160]}")

        text = "\n".join(parts)
        return text[:max_chars]


class ContextEngine:
    """Monta contextos relevantes sob demanda."""

    def __init__(
        self,
        state: GlobalState,
        working_memory: WorkingMemory,
        memory_system: MemorySystem,
        logger: Logger | None = None,
        max_memories: int = 5,
    ) -> None:
        self._state = state
        self._working = working_memory
        self._memory = memory_system
        self._logger = logger
        self._max_memories = max_memories

    def _select_long_term(self, query: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Seleciona memórias de longo prazo relevantes.

        Busca por relevância de texto (query), ordena por importância
        e limita a quantidade — não envia tudo para o LLM.
        """
        limit = limit or self._max_memories
        entries = self._memory.semantic.search(query=query, limit=limit * 2)
        return [
            {
                "id": e.id,
                "title": e.title,
                "content": e.content,
                "category": e.category.value,
                "importance": e.importance,
                "tags": list(e.tags),
            }
            for e in entries[:limit]
        ]

    def build(
        self,
        user_input: str = "",
        events: list[Event] | None = None,
        include_long_term: bool = True,
    ) -> ContextBundle:
        """Constrói o contexto da tarefa atual."""
        events = events or self._state.recent_events(10)

        bundle = ContextBundle(
            user_input=user_input,
            current_task=self._working.snapshot(),
            current_goal=self._state.current_goal,
            current_mode=self._state.current_mode,
            recent_events=[{"type": e.event_type, "source": e.source} for e in events],
            system_snapshot=self._state.snapshot(),
            long_term_memories=(
                self._select_long_term(user_input) if include_long_term and user_input else []
            ),
            notes={
                key: self._working.recall(key)
                for key in ("last_intent", "last_module", "pending_goal")
            },
        )
        return bundle

    def refresh(self) -> None:
        """Reconstrói o contexto da tarefa atual (fim de ciclo)."""
        return None

    def get_stats(self) -> dict[str, Any]:
        return {
            "max_memories": self._max_memories,
            "recent_events": len(self._state.recent_events(20)),
        }
