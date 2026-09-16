"""Modelos de dados para o sistema de planejamento de execução.

Define as estruturas ExecutionPlan, PlanAction, ActionDependency,
TemporalInfo e ActionTrigger que representam um plano estruturado
de múltiplas ações derivado de linguagem natural.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    """Tipos de ação que o planner reconhece."""

    SHUTDOWN = "shutdown"
    RESTART = "restart"
    LOCK = "lock"
    SLEEP = "sleep"
    WAKE = "wake"
    SCHEDULE_SHUTDOWN = "schedule_shutdown"
    SCHEDULE_WAKE = "schedule_wake"
    CANCEL_SCHEDULE = "cancel_schedule"
    OPEN_APP = "open_app"
    OPEN_URL = "open_url"
    OPEN_BROWSER = "open_browser"
    SEARCH_WEB = "search_web"
    SEARCH_FILES = "search_files"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    RUN_COMMAND = "run_command"
    REMINDER_CREATE = "reminder_create"
    REMINDER_CANCEL = "reminder_cancel"
    MEMORY_STORE = "memory_store"
    MEMORY_SEARCH = "memory_search"
    EMAIL_LIST = "email_list"
    EMAIL_READ = "email_read"
    EMAIL_SEND = "email_send"
    SYSTEM_STATUS = "system_status"
    WAIT = "wait"
    CONFIRM = "confirm"
    UNKNOWN = "unknown"


class RelationType(str, Enum):
    """Tipos de relação entre ações."""

    SEQUENTIAL = "sequential"
    TEMPORAL = "temporal"
    CONDITIONAL = "conditional"
    DEPENDENCY = "dependency"
    PARALLEL = "parallel"


class ActionStatus(str, Enum):
    """Status de uma ação no plano."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class PlanStatus(str, Enum):
    """Status geral do plano."""

    DRAFT = "draft"
    VALIDATED = "validated"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TemporalInfo:
    """Informação temporal associada a uma ação."""

    time_str: str | None = None
    time_value: datetime | None = None
    relative_hours: float | None = None
    relative_minutes: float | None = None
    is_relative: bool = False
    is_recurring: bool = False
    recurring_interval_minutes: int | None = None
    day_of_week: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.time_str:
            d["time_str"] = self.time_str
        if self.time_value:
            d["time_value"] = self.time_value.isoformat()
        if self.relative_hours is not None:
            d["relative_hours"] = self.relative_hours
        if self.relative_minutes is not None:
            d["relative_minutes"] = self.relative_minutes
        d["is_relative"] = self.is_relative
        d["is_recurring"] = self.is_recurring
        if self.recurring_interval_minutes is not None:
            d["recurring_interval_minutes"] = self.recurring_interval_minutes
        if self.day_of_week:
            d["day_of_week"] = self.day_of_week
        return d


@dataclass
class ActionTrigger:
    """Gatilho condicional para execução de uma ação."""

    trigger_type: str = ""
    trigger_event: str = ""
    trigger_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.trigger_type:
            d["trigger_type"] = self.trigger_type
        if self.trigger_event:
            d["trigger_event"] = self.trigger_event
        if self.trigger_params:
            d["trigger_params"] = self.trigger_params
        return d


@dataclass
class ActionDependency:
    """Define uma dependência entre duas ações."""

    source_id: str = ""
    target_id: str = ""
    relation: RelationType = RelationType.SEQUENTIAL
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation.value,
            "description": self.description,
        }


@dataclass
class PlanAction:
    """Uma ação individual dentro de um ExecutionPlan."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    action_type: ActionType = ActionType.UNKNOWN
    description: str = ""
    tool_name: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    temporal: TemporalInfo | None = None
    trigger: ActionTrigger | None = None
    depends_on: list[str] = field(default_factory=list)
    relation: RelationType = RelationType.SEQUENTIAL
    status: ActionStatus = ActionStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None
    confirmation_required: bool = False
    safety_level: str = "safe"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "action_type": self.action_type.value,
            "description": self.description,
            "status": self.status.value,
        }
        if self.tool_name:
            d["tool_name"] = self.tool_name
        if self.parameters:
            d["parameters"] = self.parameters
        if self.temporal:
            d["temporal"] = self.temporal.to_dict()
        if self.trigger:
            d["trigger"] = self.trigger.to_dict()
        if self.depends_on:
            d["depends_on"] = self.depends_on
        if self.relation != RelationType.SEQUENTIAL:
            d["relation"] = self.relation.value
        if self.result:
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
        if self.confirmation_required:
            d["confirmation_required"] = True
        if self.safety_level != "safe":
            d["safety_level"] = self.safety_level
        return d


@dataclass
class ExecutionPlan:
    """Plano de execução estruturado derivado de linguagem natural.

    Contém múltiplas ações, suas dependências, condições e ordem
    de execução. Serve como interface entre a compreensão semântica
    e a execução real das ações.
    """

    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    original_text: str = ""
    actions: list[PlanAction] = field(default_factory=list)
    dependencies: list[ActionDependency] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.now)
    executed_at: datetime | None = None
    completed_at: datetime | None = None
    errors: list[str] = field(default_factory=list)
    summary: str = ""
    needs_confirmation: bool = False
    confirmation_message: str = ""

    def add_action(self, action: PlanAction) -> None:
        """Adiciona uma ação ao plano."""
        self.actions.append(action)

    def get_action(self, action_id: str) -> PlanAction | None:
        """Busca uma ação pelo ID."""
        for a in self.actions:
            if a.id == action_id:
                return a
        return None

    def get_ready_actions(self) -> list[PlanAction]:
        """Retorna ações que estão prontas para execução.

        Uma ação está pronta quando:
        - status é PENDING
        - todas as dependências (depends_on) estão COMPLETED
        - não é condicional sem trigger ativo
        """
        ready = []
        for action in self.actions:
            if action.status != ActionStatus.PENDING:
                continue
            deps_met = all(
                self.get_action(dep_id) is not None
                and self.get_action(dep_id).status == ActionStatus.COMPLETED
                for dep_id in action.depends_on
            )
            if deps_met:
                ready.append(action)
        return ready

    def get_sequential_order(self) -> list[PlanAction]:
        """Retorna ações em ordem sequencial (topological sort).

        Ações em paralelo (mesmo nível) são agrupadas.
        """
        in_degree: dict[str, int] = {a.id: 0 for a in self.actions}
        for a in self.actions:
            for dep_id in a.depends_on:
                if dep_id in in_degree:
                    in_degree[a.id] += 1

        result: list[PlanAction] = []
        queue = [a for a in self.actions if in_degree[a.id] == 0]

        while queue:
            level_size = len(queue)
            level_actions = queue[:level_size]
            result.extend(sorted(level_actions, key=lambda a: a.id))
            queue = queue[level_size:]

            for a in level_actions:
                for other in self.actions:
                    if a.id in other.depends_on:
                        in_degree[other.id] -= 1
                        if in_degree[other.id] == 0:
                            queue.append(other)

        return result

    def is_complete(self) -> bool:
        """Verifica se todas as ações foram concluídas."""
        return all(
            a.status in (ActionStatus.COMPLETED, ActionStatus.SKIPPED, ActionStatus.CANCELLED)
            for a in self.actions
        )

    def has_failures(self) -> bool:
        """Verifica se alguma ação falhou."""
        return any(a.status == ActionStatus.FAILED for a in self.actions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "original_text": self.original_text,
            "actions": [a.to_dict() for a in self.actions],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "errors": self.errors,
            "summary": self.summary,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_message": self.confirmation_message,
        }

    def to_human_summary(self) -> str:
        """Gera resumo legível do plano para o usuário."""
        if self.summary:
            return self.summary
        lines: list[str] = []
        order = self.get_sequential_order()
        for i, action in enumerate(order, 1):
            prefix = ""
            if action.temporal and action.temporal.time_str:
                prefix = f"({action.temporal.time_str}) "
            elif action.trigger and action.trigger.trigger_event:
                event_desc = {
                    "system_start": "quando ligar",
                    "application_ready": "quando abrir",
                    "task_complete": "quando terminar",
                }.get(action.trigger.trigger_event, action.trigger.trigger_event)
                prefix = f"({event_desc}) "
            lines.append(f"{i}. {prefix}{action.description}")
        return "\n".join(lines)
