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
        - SafetyManager可供（se injetado）→ enriquece classificação
          com níveis de permissão (SAFE/CAUTION/DANGER/CRITICAL).
    """

    MAX_PARAM_SIZE = 4096

    def __init__(self, command_registry=None, logger: Logger | None = None,
                 safety_manager=None) -> None:
        self._registry = command_registry
        self._logger = logger
        self._safety = safety_manager
        self._denied_count = 0
        self._approved_count = 0
        self._audited: list[str] = []
        self._security_log: list[dict] = []

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
            self._log_security("approved", decision, "exit_always_allowed")
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
                self._log_security("denied", decision, f"param_{key}_too_large")
                return result

        # Allowlist de capacidades
        if module not in self._capabilities():
            result = GateResult(
                GateOutcome.DENIED,
                f"capacidade desconhecida '{module}' fora da allowlist",
                decision,
            )
            self._record_denial(result)
            self._log_security("denied", decision, f"unknown_capability_{module}")
            if self._logger:
                self._logger.warning(
                    f"SecurityGate: negada capacidade desconhecida '{module}' "
                    f"(fonte: {decision.source})"
                )
            return result

        # Enriquecimento via SafetyManager (se disponível)
        risk = decision.risk
        action_name = decision.action
        if self._safety is not None:
            from modules.safety import SafetyLevel
            level = self._safety.get_action_level(action_name)
            # Mapear SafetyLevel → risk numérico (se o risk do Decision for mais baixo)
            level_to_risk = {
                SafetyLevel.SAFE: 1,
                SafetyLevel.CAUTION: 2,
                SafetyLevel.DANGER: 3,
                SafetyLevel.CRITICAL: 4,
            }
            safety_risk = level_to_risk.get(level, risk)
            risk = max(risk, safety_risk)  # Usar o mais alto

        # Classificação de risco
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
        self._log_security("approved" if result.is_allowed else "denied", decision, result.reason)
        return result

    def _record_denial(self, result: GateResult) -> None:
        self._denied_count += 1
        result.decision.approved = False

    def _log_security(self, action: str, decision: Decision, reason: str) -> None:
        """Unified security audit log entry."""
        from datetime import datetime
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "module": decision.module,
            "decision_action": decision.action,
            "risk": decision.risk,
            "source": decision.source,
            "reason": reason,
        }
        self._security_log.append(entry)

    def get_security_log(self, limit: int = 50) -> list[dict]:
        """Retorna últimas entradas do security log unificado."""
        return self._security_log[-limit:]

    def get_stats(self) -> dict[str, Any]:
        return {
            "approved": self._approved_count,
            "denied": self._denied_count,
            "audited": len(self._audited),
            "capabilities": len(self._capabilities()),
            "security_log_entries": len(self._security_log),
        }
