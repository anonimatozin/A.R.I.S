"""Feedback Engine do A.R.I.S.

Transforma o resultado de uma ação em aprendizado. Usa o resultado
para:

    - restaurar a memória de trabalho se preciso;
    - gerar experiência episódica;
    - registrar falha no estado; e
    - alimentar o conjunto de aprendizado (LearningStore).

Nada aqui depende do LLM; é tudo transformação de dados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.neural.actions.action_engine import ActionResult
from core.neural.decision.decision_engine import Decision
from core.neural.events import EVENT_ACTION_COMPLETED, Event
from core.neural.memory.system import MemorySystem
from core.neural.memory.working_memory import WorkingMemory
from core.neural.state import GlobalState
from utils.logger import Logger


@dataclass
class FeedbackReport:
    """Feedback consolidado de uma ação executada."""
    outcome: str  # "success" | "failure"
    event: Event
    experience: dict[str, Any] | None = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "event_type": self.event.event_type,
            "experience": self.experience,
        }


class FeedbackEngine:
    """Processa aprendizagem a partir de resultados de ações."""

    def __init__(
        self,
        working: WorkingMemory,
        memory: MemorySystem,
        state: GlobalState,
        logger: Logger | None = None,
    ) -> None:
        self._working = working
        self._memory = memory
        self._state = state
        self._logger = logger
        self._ok = 0
        self._fail = 0

    def process(self, decision: Decision, result: ActionResult) -> FeedbackReport:
        """Processa o feedback de uma ação executada."""
        outcome = "success" if result.success else "failure"
        if result.success:
            self._ok += 1
        else:
            self._fail += 1
            self._state.record_failure(result.error or "falha desconhecida")

        # Restaura a memória de trabalho
        if result.success:
            self._working.complete_current_task(
                result=result.output, success=True
            )
        else:
            self._working.reflect_result(result.error or "falha", success=False)

        # Experiência episódica (recorde apenas se relevante)
        experience = self._memory.episodic.record(
            self._make_experience(decision, result, outcome)
        )

        # Evento de conclusão
        event = Event(
            event_type=EVENT_ACTION_COMPLETED,
            source="neural_core",
            payload={"module": decision.module, "action": decision.action,
                     "success": result.success},
            priority=60,
            confidence=1.0,
        )

        report = FeedbackReport(outcome=outcome, event=event, experience=experience)
        if self._logger and not result.success:
            self._logger.warning(
                f"FeedbackEngine: falha em {decision.module}/{decision.action}: "
                f"{result.error}"
            )
        return report

    def _make_experience(self, decision: Decision, result: ActionResult, outcome: str) -> dict[str, Any]:
        """Monta uma experiência episódica."""
        from core.neural.memory.system import Experience
        return Experience(
            event=f"{decision.module}/{decision.action}",
            goal=self._state.current_goal or "",
            actions=[f"{decision.module}/{decision.action}"],
            result=result.output or result.error,
            success=(outcome == "success"),
            context={"source": decision.source, "confidence": decision.confidence},
            importance=0.8 if not result.success else 0.4,
        )

    def get_stats(self) -> dict[str, int]:
        return {"success": self._ok, "failures": self._fail}
