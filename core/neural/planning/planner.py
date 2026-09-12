"""Planner do A.R.I.S.

Transforma um objetivo em uma sequência de passos executáveis. Nesta
fase o planejador constrói planos a partir das capacidades existentes
(registry) — execução guiada por passos, com prerrequisitos simples.

Não há reinforcement learning: o plano é determinístico e derivado das
capacidades reais do sistema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.advanced_interpreter import Intent
from core.neural.reasoning.reasoning_router import DeterministicEngine
from utils.logger import Logger

# Templates de plano (objetivo → passos de intenção)
GOAL_TEMPLATES: list[tuple[str, str, list[dict[str, Any]]]] = [
    ("%cpu", "objetivo de monitorar o sistema",
     [{"module": "sys", "action": "analyze", "params": {}}]),
    ("%clima", "objetivo de consultar o clima",
     [{"module": "weather", "action": "now", "params": {"city": ""}}]),
    ("%pesquisar", "objetivo de pesquisa na web",
     [{"module": "websearch", "action": "search", "params": {"query": ""}}]),
    ("%lembrar", "objetivo de armazenar memória",
     [{"module": "remember", "action": "execute", "params": {"content": ""}}]),
]


@dataclass
class PlanStep:
    """Um passo de um plano."""
    module: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def to_intent(self) -> Intent:
        return Intent(module=self.module, action=self.action,
                      params=self.params, confidence=0.9)

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "action": self.action,
                "params": dict(self.params), "rationale": self.rationale}


@dataclass
class Plan:
    """Um plano completo."""
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    status: str = "created"  # created | running | completed | failed
    current_step: int = -1

    def next_step(self) -> PlanStep | None:
        if self.current_step + 1 >= len(self.steps):
            return None
        self.current_step += 1
        self.status = "running"
        return self.steps[self.current_step]

    def complete(self) -> None:
        self.status = "completed"

    def fail(self, reason: str) -> None:
        self.status = "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "current_step": self.current_step,
        }


class Planner:
    """Planeja a partir de capacidades reais."""

    def __init__(self, command_registry=None, logger: Logger | None = None) -> None:
        self._registry = command_registry
        self._logger = logger
        self._deterministic = DeterministicEngine(logger=logger)

    # ── Construção de planos ─────────────────────────────────

    def build(self, goal: str) -> Plan:
        """Constrói um plano para o objetivo, se conhecido."""
        plan = Plan(goal=goal)

        # 1. Template conhecido
        keyword = goal.strip().lower()
        for key, _description, steps in GOAL_TEMPLATES:
            if key in keyword:
                plan.steps = [
                    PlanStep(module=s["module"], action=s["action"], params=s["params"])
                    for s in steps
                ]
                if self._logger:
                    self._logger.debug(f"Planner: plano via template para {goal!r}")
                return plan

        # 2. Regra determinística
        intents = self._deterministic.parse(goal)
        if intents:
            plan.steps = [
                PlanStep(module=i.module, action=i.action, params=i.params or {})
                for i in intents
            ]
            if self._logger:
                self._logger.debug(f"Planner: plano via determinístico para {goal!r}")
            return plan

        # 3. Plano vazio (indica que não há execução estática)
        plan.status = "completed"
        return plan

    def can_plan(self, goal: str) -> bool:
        """Indica se há um plano conhecido para o objetivo."""
        return bool(self.build(goal).steps)

    def get_stats(self) -> dict[str, Any]:
        return {"templates": len(GOAL_TEMPLATES)}
