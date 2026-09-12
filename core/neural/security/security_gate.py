"""Security Gate do A.R.I.S.

Camada obrigatória entre decisão e execução. Classifica ações por
risco e garante que somente capacidades conhecidas sejam executadas.

Fluxo:

    Decision → Security Gate → Action

A segurança NÃO depende exclusivamente do LLM: a capacidade vem do
registry (allowlist) e o risco da classificação estrutural.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from core.neural.decision.decision_engine import Decision
from utils.logger import Logger


class GateOutcome(StrEnum):
    APPROVED = "approved"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    DENIED = "denied"


@dataclass
class GateResult:
    """Resultado da avaliação do Security Gate."""
    outcome: GateOutcome
    reason: str
    decision: Decision
    audit_required: bool = False

    @property
    def is_allowed(self) -> bool:
        return self.outcome == GateOutcome.APPROVED


class SecurityGate:
    """Portão de segurança determinístico.

    Regras:
        - ``exit`` (encerramento) é sempre permitido.
        - Módulo fora da allowlist de capacidades → DENIED.
        - Risco LOW → APPROVED.
        - Risco CAUTION/DANGER → APPROVED (auditável para DANGER).
        - Risco CRITICAL → REQUIRES_CONFIRMATION (a confirmação é
          resolvida pelo CommandRegistry, que possui o mecanismo de
          token + senha).
    """

    MAX_PARAM_SIZE = 4096

    def __init__(self, command_registry=None, logger: Logger | None = None) -> None:
        self._registry = command_registry
        self._logger = logger
        self._denied_count = 0
        self._approved_count = 0
        self._audited: list[str] = []

    def _capabilities(self) -> set[str]:
        """Conjunto de módulos conhecidos (allowlist).

        Fonte: intents registrados no CommandRegistry + módulos
        mapeados por segurança. O LLM não pode executar módulos fora
        desta lista.
        """
        caps: set[str] = set()
        if self._registry is not None:
            for module, _desc in self._registry.list_intents():
                caps.add(module)
            # Framework funciona via execute_intent; também aceitamos
            # o módulo "frameworks". Vazio por padrão (nada além do registry).
        return caps

    def approve(self, decision: Decision) -> GateResult:
        """Avalia uma decisão contra as políticas de segurança."""
        module = decision.module

        # Saída/emergência sempre permitida
        if module == "exit":
            result = GateResult(GateOutcome.APPROVED, "encerramento autorizado", decision)
            self._approved_count += 1
            return result

        # Validação de entrada básica (evita payloads absurdos)
        for key, value in decision.parameters.items():
            if len(str(value)) > self.MAX_PARAM_SIZE:
                result = GateResult(
                    GateOutcome.DENIED,
                    f"parâmetro '{key}' excede o tamanho máximo",
                    decision,
                )
                self._record_denial(result)
                return result

        # Allowlist de capacidades
        if module not in self._capabilities():
            result = GateResult(
                GateOutcome.DENIED,
                f"capacidade desconhecida '{module}' fora da allowlist",
                decision,
            )
            self._record_denial(result)
            if self._logger:
                self._logger.warning(
                    f"SecurityGate: negada capacidade desconhecida '{module}' "
                    f"(fonte: {decision.source})"
                )
            return result

        # Classificação de risco
        risk = decision.risk
        if risk >= 4:  # CRITICAL
            result = GateResult(
                GateOutcome.REQUIRES_CONFIRMATION,
                "ação CRITICAL requer confirmação do operador",
                decision,
                audit_required=True,
            )
        elif risk >= 3:  # DANGER
            result = GateResult(
                GateOutcome.APPROVED,
                "ação DANGER executada com auditoria",
                decision,
                audit_required=True,
            )
        else:  # LOW / CAUTION
            result = GateResult(GateOutcome.APPROVED, "ação permitida", decision)

        self._approved_count += 1
        if result.audit_required:
            self._audited.append(f"{module}/{decision.action}")
        decision.approved = result.is_allowed
        return result

    def _record_denial(self, result: GateResult) -> None:
        self._denied_count += 1
        result.decision.approved = False

    def get_stats(self) -> dict[str, Any]:
        return {
            "approved": self._approved_count,
            "denied": self._denied_count,
            "audited": len(self._audited),
            "capabilities": len(self._capabilities()),
        }
