"""Decision Engine do A.R.I.S.

Recebe objetivo, contexto, ações disponíveis, resultado de raciocínio
e estado do sistema; retorna uma decisão estruturada. A saída
arbitrária do LLM nunca é executada diretamente: ela vira apenas um
``Decision`` que ainda passa pelo Security Gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.advanced_interpreter import Intent
from core.neural.context.context_engine import ContextBundle
from utils.logger import Logger

# Riscos padrão por intenção (1 = LOW ... 4 = CRITICAL)
DEFAULT_RISK = {
    "weather": 1, "websearch": 1, "sys": 1, "search": 1, "remember": 1,
    "config": 1, "speak": 1, "context": 1, "knowledge": 1, "safety": 1,
    "digest": 1, "calc": 1,
    "desktop": 2, "scheduler": 2, "notify": 2, "entertainment": 2,
    "turbo": 2, "awareness": 2, "redact": 2, "skills": 2, "dictation": 2,
    "browser": 2, "agents": 2,
    "exit": 4,
}


@dataclass
class Decision:
    """Decisão estruturada a ser avaliada pelo Security Gate."""
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    risk: int = 2
    rationale: str = ""
    source: str = "llm"
    module: str = ""
    approved: bool | None = None
    decision_id: str = field(default_factory=lambda: datetime.now().strftime("%H%M%S%f")[:12])

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "module": self.module,
            "action": self.action,
            "parameters": dict(self.parameters),
            "confidence": self.confidence,
            "risk": self.risk,
            "rationale": self.rationale,
            "source": self.source,
            "approved": self.approved,
        }


class DecisionEngine:
    """Constrói decisões estruturadas a partir de intenções."""

    def __init__(self, security_levels: dict[str, int] | None = None, logger: Logger | None = None) -> None:
        self._risk_map = dict(DEFAULT_RISK)
        if security_levels:
            self._risk_map.update({k: int(v) for k, v in security_levels.items()})
        self._logger = logger
        self._made = 0
        self._denied_by_risk = 0

    def risk_for(self, module: str) -> int:
        """Determina o risco de uma intenção."""
        return self._risk_map.get(module, 2)

    def decide(
        self,
        intent: Intent,
        goal: str = "",
        context: ContextBundle | None = None,
        source: str = "llm",
    ) -> Decision:
        """Transforma uma intenção (da IA ou determinística) em decisão."""
        self._made += 1
        risk = self.risk_for(intent.module)
        decision = Decision(
            module=intent.module,
            action=intent.action or "execute",
            parameters=dict(intent.params or {}),
            confidence=max(0.0, min(1.0, intent.confidence or 0.8)),
            risk=risk,
            rationale=f"intent {intent.module}/{intent.action} (confiança {intent.confidence})",
            source=source,
        )
        if self._logger:
            self._logger.debug(
                f"DecisionEngine: {decision.module}/{decision.action} risco={risk}"
            )
        return decision

    def get_stats(self) -> dict[str, Any]:
        return {
            "decisions_made": self._made,
            "denied_by_risk": self._denied_by_risk,
            "known_intents": len(self._risk_map),
        }
