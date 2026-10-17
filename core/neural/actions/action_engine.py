"""Action Engine do A.R.I.S.

Camada de execução sobre os handlers existentes. Localiza a
capacidade, valida parâmetros, executa e captura resultado/erro,
devolvendo feedback estruturado.

Preserva o estoque de capacidades atual (22 intents + plugins) — nada
é removido; apenas ganha uma camada uniforme de execução.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.neural.decision.decision_engine import Decision
from utils.logger import Logger


@dataclass
class ActionResult:
    """Resultado estruturado de uma ação executada."""
    success: bool
    output: str = ""
    error: str = ""
    duration: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    module: str = ""
    action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": str(self.output)[:500],
            "error": str(self.error)[:500],
            "duration": round(self.duration, 3),
            "metadata": dict(self.metadata),
            "module": self.module,
            "action": self.action,
        }

    def __repr__(self) -> str:
        status = "OK" if self.success else "ERR"
        return f"ActionResult({status}, {self.module}/{self.action}, {self.duration:.2f}s)"


class ActionEngine:
    """Executa decisões aprovadas através do CommandRegistry."""

    def __init__(self, command_registry=None, logger: Logger | None = None) -> None:
        self._registry = command_registry
        self._logger = logger
        self._executed = 0
        self._failures = 0

    def locate(self, module: str) -> bool:
        """Verifica se a capacidade existe no registry."""
        if self._registry is None:
            return False
        return self._registry.has_intent(module)

    def validate(self, decision: Decision, ctx: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Valida se a decisão pode ser executada.

        Retorna (ok, mensagem). Validações atuais: existência do
        handler. A validação de parâmetros específica permanece nos
        handlers (não força mudança de comportamento).
        """
        if not self.locate(decision.module):
            return False, "capacidade não localizada"
        return True, ""

    # Marcadores que denotam FALHA real numa resposta textual de ferramenta.
    # Motivo: os handlers devolvem strings livres; sem esta convenção, uma
    # ação que falhou (ex.: "Ação desconhecida: abrir") era classificada como
    # sucesso e a ARIS confirmava em voz algo que não aconteceu.
    _FAILURE_MARKERS = (
        "ação desconhecida",
        "acao desconhecida",
        "não encontrado",
        "nao encontrado",
        "indisponível",
        "indisponivel",
        "não instalado",
        "nao instalado",
        "não foi possível",
        "nao foi possivel",
        "não pôde",
        "nao pode",
        "falha ao",
        "erro ao",
        "erro:",
        "entrada rejeitada",
        "senha incorreta",
        "cancelada pelo operador",
        "vazio",
        "sem permissão",
        "sem permissao",
        "negada",
        "requer confirmação",
        "requer confirmacao",
        "não disponível",
        "nao disponivel",
        "não implementado",
        "nao implementado",
        "não suportado",
        "nao suportado",
    )

    @classmethod
    def _looks_like_failure(cls, output: str) -> bool:
        """Detecta se uma resposta textual de ferramenta denota falha."""
        low = output.lower()
        return any(marker in low for marker in cls._FAILURE_MARKERS)

    def execute(self, decision: Decision, ctx: dict[str, Any] | None = None) -> ActionResult:
        """Executa a decisão e captura resultado/erro."""
        start = time.perf_counter()
        module = decision.module
        action = decision.action

        ok, message = self.validate(decision, ctx)
        if not ok:
            self._failures += 1
            return ActionResult(
                success=False,
                error=message,
                duration=time.perf_counter() - start,
                module=module,
                action=action,
            )

        result = self._registry.execute_intent(
            module=module,
            action=action,
            params=decision.parameters,
            **(ctx or {}),
        )

        duration = time.perf_counter() - start
        self._executed += 1

        # Registry devolve string; string de erro reconhecível denota falha
        if isinstance(result, str) and result.startswith("Erro ao executar"):
            self._failures += 1
            return ActionResult(
                success=False,
                error=result,
                duration=duration,
                module=module,
                action=action,
            )

        if isinstance(result, str):
            output = result
            # Honesty: uma resposta textual que denota falha NÃO é sucesso.
            success = not self._looks_like_failure(output)
        else:
            output = str(result) if result is not None else ""
            success = result is not None

        if not success:
            self._failures += 1

        if self._logger:
            self._logger.debug(
                f"ActionEngine: {module}/{action} sucesso={success} ({duration:.2f}s)"
            )

        return ActionResult(
            success=success,
            output=output,
            duration=duration,
            metadata={"confidence": decision.confidence, "source": decision.source},
            module=module,
            action=action,
        )

    def capabilities(self) -> list[str]:
        """Lista de capacidades disponíveis."""
        if self._registry is None:
            return []
        return [m for m, _d in self._registry.list_intents()]

    def get_stats(self) -> dict[str, int]:
        return {"executed": self._executed, "failures": self._failures}
