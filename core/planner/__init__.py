"""Módulo de planejamento de execução multi-intent.

Fornece a API pública para:
- Parse de texto em múltiplas ações estruturadas
- Análise temporal e de dependências
- Geração e execução de planos
- Resumo legível de planos

Uso:
    from core.planner import create_planner

    planner = create_planner(llm_router=router)
    plan = planner.parse("desliga o pc às 15 e liga às 16:30 e abre spotify quando ligar")
    print(plan.to_human_summary())
"""

from __future__ import annotations

from .dependencies import analyze_dependencies, classify_action_type
from .executor import PlanExecutor
from .models import (
    ActionDependency,
    ActionStatus,
    ActionTrigger,
    ActionType,
    ExecutionPlan,
    PlanAction,
    PlanStatus,
    RelationType,
    TemporalInfo,
)
from .parser import MultiIntentParser
from .segmenter import Segmenter, TextSegment
from .temporal import parse_temporal


class Planner:
    """API pública unificada do sistema de planejamento.

    Combina parsing, análise e execução em uma interface simples.
    """

    def __init__(self, llm_router=None, tool_executor=None, pc_listener_url: str = ""):
        self._parser = MultiIntentParser(llm_router=llm_router)
        self._executor = PlanExecutor(
            tool_executor=tool_executor,
            pc_listener_url=pc_listener_url,
        )
        self._plans: dict[str, ExecutionPlan] = {}

    def parse(self, text: str) -> ExecutionPlan:
        """Parse de texto em ExecutionPlan.

        Args:
            text: Texto do usuário (ex: "desliga o pc às 15 e liga às 16:30")

        Returns:
            ExecutionPlan estruturado com ações, dependências e temporal
        """
        plan = self._parser.parse(text)
        self._plans[plan.plan_id] = plan
        return plan

    def execute(self, plan: ExecutionPlan, confirm_callback=None) -> ExecutionPlan:
        """Executa um plano.

        Args:
            plan: Plano a executar
            confirm_callback: Callback para confirmação (plan->bool)

        Returns:
            Plano atualizado com resultados
        """
        return self._executor.execute(plan, confirm_callback=confirm_callback)

    def execute_text(self, text: str, confirm_callback=None) -> ExecutionPlan:
        """Parse + execute em uma chamada.

        Args:
            text: Texto do usuário
            confirm_callback: Callback para confirmação

        Returns:
            Plano executado com resultados
        """
        plan = self.parse(text)
        return self.execute(plan, confirm_callback=confirm_callback)

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        """Busca um plano pelo ID."""
        return self._plans.get(plan_id)

    def list_plans(self) -> list[ExecutionPlan]:
        """Lista todos os planos."""
        return list(self._plans.values())

    def get_status(self, plan_id: str) -> dict | None:
        """Retorna status de um plano."""
        plan = self.get_plan(plan_id)
        if plan:
            return self._executor.get_status(plan)
        return None

    def set_debug(self, debug: bool) -> None:
        """Ativa/desativa modo debug."""
        self._parser.set_debug(debug)


def create_planner(
    llm_router=None,
    tool_executor=None,
    pc_listener_url: str = "",
) -> Planner:
    """Factory function para criar um Planner configurado.

    Args:
        llm_router: Router LLM para parse semântico (opcional)
        tool_executor: Executor de tools existente (opcional)
        pc_listener_url: URL do PC listener (ex: http://192.168.0.109:8770)

    Returns:
        Planner configurado
    """
    return Planner(
        llm_router=llm_router,
        tool_executor=tool_executor,
        pc_listener_url=pc_listener_url,
    )


__all__ = [
    "Planner",
    "create_planner",
    "ExecutionPlan",
    "PlanAction",
    "ActionType",
    "ActionStatus",
    "PlanStatus",
    "RelationType",
    "TemporalInfo",
    "ActionTrigger",
    "ActionDependency",
    "PlanExecutor",
    "MultiIntentParser",
    "Segmenter",
    "TextSegment",
    "parse_temporal",
    "classify_action_type",
    "analyze_dependencies",
]
