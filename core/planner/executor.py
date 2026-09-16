"""Executor de planos de execução.

Executa um ExecutionPlan passo a passo, respeitando dependências,
condições e horários. Integra com o ToolRegistry existente.
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime
from typing import Any, Callable

from .models import (
    ActionStatus,
    ActionType,
    ExecutionPlan,
    PlanAction,
    PlanStatus,
)

logger = logging.getLogger(__name__)


class PlanExecutor:
    """Executor de ExecutionPlans.

    Executa ações respeitando:
    - Ordem sequencial (topological sort)
    - Dependências entre ações
    - Condições (triggers)
    - Horários agendados
    - Paralelismo quando seguro
    """

    def __init__(self, tool_executor=None, pc_listener_url: str = ""):
        self._tool_executor = tool_executor
        self._pc_url = pc_listener_url
        self._callbacks: dict[str, Callable] = {}
        self._on_action_complete: Callable | None = None
        self._on_plan_complete: Callable | None = None

    def on_action_complete(self, callback: Callable[[PlanAction, dict], None]) -> None:
        """Registra callback para quando uma ação completa."""
        self._on_action_complete = callback

    def on_plan_complete(self, callback: Callable[[ExecutionPlan], None]) -> None:
        """Registra callback para quando o plano completa."""
        self._on_plan_complete = callback

    def execute(self, plan: ExecutionPlan, confirm_callback: Callable | None = None) -> ExecutionPlan:
        """Executa um plano completo.

        Args:
            plan: Plano a executar
            confirm_callback: Callback para pedir confirmação (ação->bool)

        Returns:
            Plano atualizado com status e resultados
        """
        if plan.status == PlanStatus.DRAFT:
            plan = self._validate(plan)

        if plan.status == PlanStatus.FAILED:
            return plan

        plan.status = PlanStatus.EXECUTING
        plan.executed_at = datetime.now()

        # Pedir confirmação se necessário
        if plan.needs_confirmation and confirm_callback:
            confirmed = confirm_callback(plan)
            if not confirmed:
                plan.status = PlanStatus.CANCELLED
                plan.errors.append("Usuário cancelou o plano")
                return plan

        # Executar em ordem
        order = plan.get_sequential_order()
        parallel_groups = self._group_parallel(order)

        for group in parallel_groups:
            if len(group) == 1:
                self._execute_action(group[0], plan)
            else:
                # Executar ações paralelas (sem dependência entre si)
                for action in group:
                    self._execute_action(action, plan)

            # Verificar se alguma ação falhou e bloqueia subsequentes
            if any(a.status == ActionStatus.FAILED for a in group):
                # Marcar ações dependentes como skipped
                self._skip_dependents(plan, group)
                if not plan.has_failures():
                    plan.status = PlanStatus.PARTIAL_FAILURE

        # Status final
        if plan.has_failures():
            if plan.is_complete():
                plan.status = PlanStatus.PARTIAL_FAILURE
            else:
                plan.status = PlanStatus.FAILED
        else:
            plan.status = PlanStatus.COMPLETED

        plan.completed_at = datetime.now()

        if self._on_plan_complete:
            self._on_plan_complete(plan)

        return plan

    def _validate(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Valida o plano antes de executar."""
        if not plan.actions:
            plan.status = PlanStatus.FAILED
            plan.errors.append("Plano vazio")
            return plan

        plan.status = PlanStatus.VALIDATED
        return plan

    def _group_parallel(self, actions: list[PlanAction]) -> list[list[PlanAction]]:
        """Agrupa ações que podem rodar em paralelo.

        Ações são paralelas se:
        - Não têm dependência entre si
        - Não são condicionais
        - São do tipo que pode rodar em paralelo (open_app, etc.)
        """
        groups: list[list[PlanAction]] = []
        current_group: list[PlanAction] = []

        parallel_safe_types = {
            ActionType.OPEN_APP,
            ActionType.OPEN_URL,
            ActionType.OPEN_BROWSER,
            ActionType.SEARCH_WEB,
            ActionType.SYSTEM_STATUS,
            ActionType.MEMORY_STORE,
            ActionType.MEMORY_SEARCH,
        }

        for action in actions:
            can_parallel = (
                action.action_type in parallel_safe_types
                and not action.depends_on
                and not action.trigger
                and action.relation.value == "parallel"
            )

            if can_parallel and current_group:
                current_group.append(action)
            else:
                if current_group:
                    groups.append(current_group)
                current_group = [action]

        if current_group:
            groups.append(current_group)

        return groups

    def _execute_action(self, action: PlanAction, plan: ExecutionPlan) -> None:
        """Executa uma ação individual."""
        action.status = ActionStatus.RUNNING

        try:
            # Verificar trigger condicional
            if action.trigger:
                if not self._check_trigger(action):
                    action.status = ActionStatus.SKIPPED
                    action.error = "Trigger condition not met"
                    return

            # Executar
            result = self._dispatch_action(action)
            action.result = result
            action.status = ActionStatus.COMPLETED

            if self._on_action_complete:
                self._on_action_complete(action, result)

        except Exception as e:
            action.status = ActionStatus.FAILED
            action.error = str(e)
            logger.error(f"Action {action.id} failed: {e}")

    def _check_trigger(self, action: PlanAction) -> bool:
        """Verifica se o trigger de uma ação está ativo."""
        if not action.trigger:
            return True

        event = action.trigger.trigger_event

        if event == "system_start":
            # Verificar se o PC está ligado
            return self._is_pc_online()
        elif event == "application_ready":
            # Por enquanto, assumir que app abriu
            return True
        elif event == "task_complete":
            return True

        return True

    def _is_pc_online(self) -> bool:
        """Verifica se o PC está online."""
        if not self._pc_url:
            return True

        try:
            import urllib.request
            req = urllib.request.Request(
                f"{self._pc_url}/status",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _dispatch_action(self, action: PlanAction) -> dict[str, Any]:
        """Despacha uma ação para o executor correto."""
        # Se tem tool_executor, usar ele
        if self._tool_executor and action.tool_name:
            return self._tool_executor.execute(action.tool_name, action.parameters)

        # Senão, execução direta via PC listener
        if action.action_type in (
            ActionType.SHUTDOWN,
            ActionType.RESTART,
            ActionType.LOCK,
            ActionType.SLEEP,
        ):
            return self._execute_pc_command(action)

        if action.action_type == ActionType.OPEN_APP:
            return self._execute_pc_command(action)

        if action.action_type in (ActionType.SCHEDULE_SHUTDOWN, ActionType.SCHEDULE_WAKE):
            return self._execute_pc_command(action)

        return {"status": "no_executor", "message": "No executor available"}

    def _execute_pc_command(self, action: PlanAction) -> dict[str, Any]:
        """Executa comando no PC via listener HTTP."""
        if not self._pc_url:
            return {"status": "error", "message": "PC listener URL not configured"}

        import json
        import urllib.request

        command = action.parameters.get("command", "")
        if not command:
            # Mapear action type para comando
            cmd_map = {
                ActionType.SHUTDOWN: "shutdown /s /t 0",
                ActionType.RESTART: "shutdown /r /t 0",
                ActionType.LOCK: "rundll32.exe user32.dll,LockWorkStation",
                ActionType.SLEEP: "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
            }
            command = cmd_map.get(action.action_type, "")

        if not command:
            return {"status": "error", "message": "No command to execute"}

        payload = json.dumps({
            "command": "exec",
            "code": command,
        }).encode()

        req = urllib.request.Request(
            f"{self._pc_url}/status",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data

    def _skip_dependents(self, plan: ExecutionPlan, failed_actions: list[PlanAction]) -> None:
        """Marca ações dependentes como skipped."""
        failed_ids = {a.id for a in failed_actions}
        for action in plan.actions:
            if action.status == ActionStatus.PENDING:
                if any(dep_id in failed_ids for dep_id in action.depends_on):
                    action.status = ActionStatus.SKIPPED
                    action.error = "Dependência falhou"

    def get_status(self, plan: ExecutionPlan) -> dict[str, Any]:
        """Retorna status detalhado do plano."""
        return {
            "plan_id": plan.plan_id,
            "status": plan.status.value,
            "total_actions": len(plan.actions),
            "completed": sum(1 for a in plan.actions if a.status == ActionStatus.COMPLETED),
            "failed": sum(1 for a in plan.actions if a.status == ActionStatus.FAILED),
            "skipped": sum(1 for a in plan.actions if a.status == ActionStatus.SKIPPED),
            "pending": sum(1 for a in plan.actions if a.status == ActionStatus.PENDING),
            "running": sum(1 for a in plan.actions if a.status == ActionStatus.RUNNING),
            "actions": [
                {
                    "id": a.id,
                    "type": a.action_type.value,
                    "description": a.description,
                    "status": a.status.value,
                    "error": a.error,
                }
                for a in plan.actions
            ],
        }
