"""Exceções do agente. Ferramentas devolvem ToolResult; exceções ficam para erros reais."""

from __future__ import annotations

from typing import Literal

ProviderKind = Literal["rate_limit", "auth", "bad_request", "server", "network", "tool_format"]


class ArisAgentError(Exception):
    """Erro base do pacote aris_agent."""


class ToolError(ArisAgentError):
    """Falha de execução de uma ferramenta (deve virar ToolResult(ok=False))."""


class ProviderError(ArisAgentError):
    """Falha no provedor de LLM, classificada para permitir retry seletivo."""

    def __init__(
        self,
        message: str,
        *,
        kind: ProviderKind = "server",
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after_s = retry_after_s


class PolicyDenied(ArisAgentError):  # noqa: N818 - nome definido pelo contrato
    """Ação barrada pela política de segurança (raiz não permitida, comando proibido...)."""
