"""Dublês de teste compartilhados. Não alterar sem pedido em docs/agent/pedidos/.

Servem para testar uma parte sem depender das outras (LLM, memória, skills,
executor de segurança). Nunca use em produção.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable

from .contract.errors import ProviderError, ToolError
from .contract.types import (
    ChatMessage,
    ConfirmRequest,
    LLMResponse,
    MemoryItem,
    Risk,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSpec,
    Usage,
)
from .tools.registry import ToolRegistry


class FakeLLM:
    """LLM de mentira: devolve os ``ChatMessage`` do roteiro, em ordem.

    Guarda cada chamada em ``self.calls`` (dict com messages/tools/kwargs)
    para os testes fazerem assert.
    """

    def __init__(self, script: Iterable[ChatMessage] = ()) -> None:
        self.script: list[ChatMessage] = list(script)
        self.calls: list[dict] = []

    @property
    def remaining(self) -> int:
        return len(self.script)

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        *,
        difficulty: str = "normal",
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools) if tools else [],
                "difficulty": difficulty,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if not self.script:
            raise ProviderError("FakeLLM: roteiro esgotado", kind="server")
        message = self.script.pop(0)
        content = message.content or ""
        return LLMResponse(
            message=message,
            usage=Usage(
                prompt_tokens=max(1, len(json.dumps(
                    [m.content for m in messages], ensure_ascii=False
                )) // 4),
                completion_tokens=max(1, len(content) // 4),
            ),
            provider="fake",
            model="fake",
            finish_reason="tool_calls" if message.tool_calls else "stop",
        )

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"<FakeLLM {self.remaining} mensagens restantes>"


class FakeMemory:
    """Memória em RAM: implementa ``Memory`` sem SQLite nem disco."""

    def __init__(self) -> None:
        self.items: dict[str, MemoryItem] = {}
        self.turns: dict[str, list[ChatMessage]] = {}

    def remember(self, text: str, *, kind: str = "fact", tags: tuple = ()) -> str:
        item_id = uuid.uuid4().hex[:12]
        self.items[item_id] = MemoryItem(
            id=item_id,
            text=text,
            kind=kind,
            score=1.0,
            created_at=time.time(),
            tags=tuple(tags),
        )
        return item_id

    def recall(self, query: str, k: int = 5, kinds: tuple | None = None) -> list[MemoryItem]:
        terms = {t for t in str(query).lower().split() if t}
        found = [
            item
            for item in self.items.values()
            if kinds is None or item.kind in kinds
            if not terms or any(t in item.text.lower() for t in terms)
        ]
        found.sort(key=lambda i: i.created_at, reverse=True)
        return found[: max(0, k)]

    def forget(self, item_id: str) -> bool:
        return self.items.pop(item_id, None) is not None

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        self.turns.setdefault(session_id, []).append(
            ChatMessage(role=role, content=content)  # type: ignore[arg-type]
        )

    def recent_turns(self, session_id: str, n: int = 10) -> list[ChatMessage]:
        return list(self.turns.get(session_id, []))[-max(0, n) :]


class FakeSkills:
    """Catálogo de skills em RAM: implementa ``SkillCatalog``."""

    def __init__(self, skills: dict[str, tuple[str, str]] | None = None) -> None:
        # nome -> (descrição, corpo)
        self.skills: dict[str, tuple[str, str]] = dict(skills or {})

    def add(self, name: str, description: str, body: str) -> None:
        self.skills[name] = (description, body)

    def names(self) -> list[str]:
        return sorted(self.skills)

    def catalog_prompt(self) -> str:
        return "\n".join(f"{name}: {desc}" for name, (desc, _body) in sorted(self.skills.items()))

    def load(self, name: str) -> str:
        if name not in self.skills:
            raise KeyError(f"skill desconhecida: {name}")
        return self.skills[name][1]


ECHO_SPEC = ToolSpec(
    name="echo",
    description="Devolve os argumentos recebidos (ferramenta de teste).",
    parameters={"type": "object", "properties": {}, "additionalProperties": True},
    risk=Risk.READ,
    tags=("teste",),
)


class EchoTool:
    """Ferramenta READ que devolve os argumentos."""

    spec = ECHO_SPEC

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(
            ok=True,
            content=json.dumps(args, ensure_ascii=False, sort_keys=True, default=str),
            data=dict(args),
        )


class AutoConfirm:
    """ConfirmFn que devolve sempre ``answer`` e guarda os pedidos recebidos."""

    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.requests: list[ConfirmRequest] = []

    def __call__(self, request: ConfirmRequest) -> bool:
        self.requests.append(request)
        return self.answer


class PassthroughExecutor:
    """ToolExecutor sem política: só busca a ferramenta no registry e roda.

    Serve para testar a Parte 7 antes de existir a Parte 5.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry if registry is not None else ToolRegistry()
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall, ctx: ToolContext, confirm=None) -> ToolResult:
        self.calls.append(call)
        try:
            tool = self.registry.get(call.name)
        except ToolError as exc:
            return ToolResult(ok=False, error=str(exc))
        run = getattr(tool, "run", None)
        if not callable(run):
            return ToolResult(ok=False, error=f"ferramenta {call.name} sem run()")
        try:
            return run(dict(call.arguments or {}), ctx)
        except Exception as exc:  # noqa: BLE001 - nada escapa para o laço
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


__all__ = [
    "AutoConfirm",
    "ECHO_SPEC",
    "EchoTool",
    "FakeLLM",
    "FakeMemory",
    "FakeSkills",
    "PassthroughExecutor",
]
