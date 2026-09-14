"""Cognitive Workspace do A.R.I.S.

Snapshot leve e reconstruído sob demanda que agrega o estado atual
do sistema cognitivo em um único objeto imutável. Não é um estado
global mutável — é reconstruído a cada ciclo ou sob demanda.

Campos:
    focus           : descrição textual do foco atual
    recent_events   : eventos já filtrados pela atenção (últimos N)
    active_entities : entidades relevantes ao contexto corrente
    current_goal    : objetivo dominante (ou None)
    current_task    : último comando/intent processado
    hypotheses      : hipóteses ativas (vazio por enquanto)
    proposals       : propostas pendentes (vazio — fase futura)
    budget          : orçamento computacional (CPU/RAM via psutil)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.neural.attention.attention_engine import (
    AggregatedEvent,
    AttentionEngine,
    AttentionLevel,
)
from core.neural.events import Event
from core.neural.memory.system import MemorySystem
from core.neural.memory.working_memory import WorkingMemory
from core.neural.state import GlobalState
from core.neural.world_model import WorldModel


@dataclass(frozen=True)
class ComputationalBudget:
    """Snapshot leve do orçamento computacional."""
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    ram_available_gb: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
            "ram_available_gb": round(self.ram_available_gb, 2),
        }


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Snapshot imutável do workspace cognitivo.

    Reconstruído sob demanda — não armazenado como estado global.
    """
    focus: str = ""
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    active_entities: list[dict[str, Any]] = field(default_factory=list)
    current_goal: str | None = None
    current_task: str = ""
    hypotheses: list[str] = field(default_factory=list)
    proposals: list[str] = field(default_factory=list)
    budget: ComputationalBudget = field(default_factory=ComputationalBudget)

    def to_dict(self) -> dict[str, Any]:
        return {
            "focus": self.focus,
            "recent_events": list(self.recent_events),
            "active_entities": list(self.active_entities),
            "current_goal": self.current_goal,
            "current_task": self.current_task,
            "hypotheses": list(self.hypotheses),
            "proposals": list(self.proposals),
            "budget": self.budget.to_dict(),
        }

    def to_prompt_str(self, max_chars: int = 2000) -> str:
        """Formata o snapshot para uso em prompts."""
        parts: list[str] = []
        if self.focus:
            parts.append(f"Foco: {self.focus}")
        if self.current_goal:
            parts.append(f"Objetivo: {self.current_goal}")
        if self.current_task:
            parts.append(f"Tarefa: {self.current_task}")
        if self.recent_events:
            events_str = " | ".join(
                f"{e.get('type', '?')}({e.get('level', '?')})"
                for e in self.recent_events[-5:]
            )
            parts.append(f"Eventos: {events_str}")
        if self.active_entities:
            entities_str = ", ".join(
                e.get("name", "?") for e in self.active_entities[:5]
            )
            parts.append(f"Entidades: {entities_str}")
        if self.budget.cpu_percent > 0:
            parts.append(
                f"CPU: {self.budget.cpu_percent:.0f}% | "
                f"RAM: {self.budget.ram_percent:.0f}%"
            )
        text = "\n".join(parts)
        return text[:max_chars]


def _get_budget() -> ComputationalBudget:
    """Obtém orçamento computacional via psutil (se disponível)."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory()
        return ComputationalBudget(
            cpu_percent=cpu,
            ram_percent=mem.percent,
            ram_available_gb=mem.available / (1024**3),
        )
    except ImportError:
        return ComputationalBudget()


class CognitiveWorkspace:
    """Constrói snapshots do workspace cognitivo sob demanda.

    Não mantém estado próprio — lê de GlobalState, WorkingMemory,
    KnowledgeGraph e AttentionEngine para montar o snapshot.
    """

    def __init__(
        self,
        state: GlobalState,
        working: WorkingMemory,
        attention: AttentionEngine,
        knowledge_graph: Any | None = None,
        memory_system: MemorySystem | None = None,
        world_model: WorldModel | None = None,
        max_events: int = 10,
        max_entities: int = 8,
        logger: Any | None = None,
    ) -> None:
        self._state = state
        self._working = working
        self._attention = attention
        self._kg = knowledge_graph
        self._memory = memory_system
        self._world = world_model
        self._max_events = max_events
        self._max_entities = max_entities
        self._logger = logger

    def build(
        self,
        events: list[Event] | None = None,
        user_intent: str | None = None,
    ) -> WorkspaceSnapshot:
        """Constrói um snapshot do workspace atual.

        Args:
            events: eventos para avaliar (usa state.recent_events se None)
            user_intent: intenção corrente do usuário (para scoring)
        """
        if events is None:
            events = self._state.recent_events(self._max_events)

        recent = self._filter_events(events, user_intent)
        entities = self._get_active_entities(user_intent)
        goal = self._state.current_goal or None
        task = self._working.snapshot().get("goal", "") or self._state.current_task
        budget = _get_budget()

        # Goals e proposals do WorldModel
        wm_goals: list[str] = []
        proposals: list[str] = []
        if self._world is not None:
            active_goals = self._world.get_active_goals()
            if active_goals and not goal:
                goal = active_goals[0].description
            wm_goals = [g.description for g in active_goals]
            overdue = self._world.get_overdue_goals()
            for g in overdue:
                proposals.append(
                    f"Objetivo atrasado: '{g.description}' "
                    f"(prazo: {g.deadline[:10] if g.deadline else '?'}). "
                    f"Atualizar ou abandonar?"
                )
            due_rems = self._world.get_due_reminders()
            for r in due_rems:
                proposals.append(f"Lembrete pendente: '{r.text}'")
            followups = self._world.check_follow_ups()
            for fu in followups:
                if fu not in proposals:
                    proposals.append(fu)

        focus = self._determine_focus(goal, task, recent)

        return WorkspaceSnapshot(
            focus=focus,
            recent_events=recent,
            active_entities=entities,
            current_goal=goal,
            current_task=task,
            hypotheses=[],
            proposals=proposals,
            budget=budget,
        )

    def _filter_events(
        self,
        events: list[Event],
        user_intent: str | None,
    ) -> list[dict[str, Any]]:
        """Filtra eventos pela atenção e retorna os relevantes."""
        if not events:
            return []

        aggregated = self._attention.aggregate_events(events, user_intent)
        result: list[dict[str, Any]] = []

        for agg in aggregated:
            if agg.level in (AttentionLevel.IGNORE,):
                continue
            result.append({
                "type": agg.representative.event_type,
                "source": agg.representative.source,
                "level": agg.level.value,
                "score": round(agg.score.score, 3) if agg.score else 0.0,
                "count": agg.count,
                "text": agg.representative.text[:120],
            })

        return result[:self._max_events]

    def _get_active_entities(self, user_intent: str | None = None) -> list[dict[str, Any]]:
        """Obtém entidades ativas do KnowledgeGraph relevantes ao contexto."""
        if self._kg is None:
            return []

        try:
            if user_intent:
                entities = self._kg.search_entities(user_intent, limit=self._max_entities)
            else:
                entities = self._kg.get_entities_by_type("pessoa", limit=self._max_entities)
                if not entities:
                    entities = self._kg.get_entities_by_type("conceito", limit=self._max_entities)
        except Exception:
            return []

        return [
            {
                "name": e.name,
                "type": e.entity_type,
                "properties": e.properties,
            }
            for e in entities
        ]

    def _determine_focus(
        self,
        goal: str | None,
        task: str,
        recent_events: list[dict[str, Any]],
    ) -> str:
        """Determina o foco atual do workspace."""
        if goal:
            return goal
        if task:
            return task
        if recent_events:
            last = recent_events[-1]
            return f"Evento: {last.get('type', '?')} ({last.get('level', '?')})"
        return "idle"
