"""Interfaces (typing.Protocol) do contrato. Não alterar sem pedido em docs/agent/pedidos/."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from .types import (
    AgentResult,
    ChatMessage,
    ConfirmFn,
    EventSink,
    LLMResponse,
    MemoryItem,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSpec,
)


@runtime_checkable
class Tool(Protocol):
    """Ferramenta executável: tem especificação e um ``run`` puro."""

    spec: ToolSpec

    def run(self, args: dict, ctx: ToolContext) -> ToolResult: ...


@runtime_checkable
class LLMClient(Protocol):
    """Cliente de LLM. ``difficulty`` escolhe a cadeia de modelos (Parte 1)."""

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        *,
        difficulty: Literal["easy", "normal", "hard"] = "normal",
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> LLMResponse: ...


@runtime_checkable
class ToolExecutor(Protocol):
    """Executa chamadas de ferramenta aplicando política. Implementado pela Parte 5.

    Toda chamada de ferramenta do agente passa por aqui.
    """

    def execute(self, call: ToolCall, ctx: ToolContext, confirm: ConfirmFn) -> ToolResult: ...


@runtime_checkable
class Memory(Protocol):
    """Memória de longo prazo + histórico da conversa. Implementado pela Parte 4."""

    def remember(self, text: str, *, kind: str = "fact", tags: tuple = ()) -> str: ...

    def recall(self, query: str, k: int = 5, kinds: tuple | None = None) -> list[MemoryItem]: ...

    def forget(self, item_id: str) -> bool: ...

    def add_turn(self, session_id: str, role: str, content: str) -> None: ...

    def recent_turns(self, session_id: str, n: int = 10) -> list[ChatMessage]: ...


@runtime_checkable
class SkillCatalog(Protocol):
    """Catálogo de skills (SKILL.md). Implementado pela Parte 6."""

    def names(self) -> list[str]: ...

    def catalog_prompt(self) -> str:
        """Lista "nome: descrição" para o prompt do sistema."""
        ...

    def load(self, name: str) -> str:
        """Corpo completo do SKILL.md + lista de recursos."""
        ...


@runtime_checkable
class Agent(Protocol):
    """Lançador do agente. Implementado pela Parte 7."""

    def run(
        self,
        user_text: str,
        session_id: str,
        confirm: ConfirmFn,
        events: EventSink | None = None,
    ) -> AgentResult: ...
