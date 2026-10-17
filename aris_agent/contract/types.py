"""Tipos imutáveis do contrato do agente. Não alterar sem pedido em docs/agent/pedidos/."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from aris_agent.config import AgentConfig


class Risk(IntEnum):
    READ = 0  # só lê; sem efeito colateral
    WRITE = 1  # cria/altera algo reversível
    EXEC = 2  # executa programa/comando, abre app, controla mouse/teclado
    DESTRUCTIVE = 3  # apaga/sobrescreve sem volta, envia dados para fora, desliga algo


@dataclass(frozen=True)
class ToolSpec:
    """Descrição de uma ferramenta entregue ao LLM e usado pela política de confirmação."""

    name: str  # snake_case, único (ex.: "pc_read_file")
    description: str  # curta e clara, para o LLM decidir quando usar
    parameters: dict  # JSON Schema do tipo "object"
    risk: Risk
    untrusted_output: bool = False  # True se a saída vem de fora (web, arquivo desconhecido)
    timeout_s: float = 30.0
    tags: tuple = ()  # ex.: ("pc", "files"), usado para selecionar ferramentas
    path_args: tuple = ()  # nomes de parâmetros que são caminhos de arquivo
    url_args: tuple = ()  # nomes de parâmetros que são URLs
    command_arg: str | None = None  # nome do parâmetro que contém um comando de shell


@dataclass
class ToolResult:
    ok: bool
    content: str = ""  # texto que o LLM verá (máx. ~8000 caracteres); "" quando ok=False
    data: Any = None  # dado estruturado opcional; NÃO vai ao LLM
    error: str | None = None
    artifacts: list = field(default_factory=list)  # caminhos de arquivos gerados


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list | None = None  # list[ToolCall] quando role == "assistant"
    tool_call_id: str | None = None  # quando role == "tool"
    name: str | None = None  # nome da ferramenta quando role == "tool"


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class LLMResponse:
    message: ChatMessage
    usage: Usage
    provider: str
    model: str
    finish_reason: str = "stop"


@dataclass
class ConfirmRequest:
    tool_name: str
    args_preview: str  # resumo legível e já sem segredos
    risk: Risk
    reason: str  # por que está pedindo confirmação
    hard_confirm: bool = False  # True = exige confirmação forte (ação em lote/destrutiva)


ConfirmFn = Callable[[ConfirmRequest], bool]


@dataclass
class ToolContext:
    session_id: str
    workdir: Path
    config: AgentConfig
    cancel: threading.Event  # setado = abortar o mais rápido possível
    taint: bool = False  # True se já entrou conteúdo não confiável nesta tarefa


@dataclass
class MemoryItem:
    id: str
    text: str
    kind: str  # "fact" | "preference" | "lesson" | "episode"
    score: float
    created_at: float
    tags: tuple = ()


@dataclass
class AgentEvent:
    type: str  # "plan" | "tool_call" | "tool_result" | "confirm" | "final" | "error"
    data: dict


EventSink = Callable[[AgentEvent], None]


@dataclass
class AgentResult:
    text: str
    steps: int
    tool_calls: int
    ok: bool
    stopped_reason: str  # "done" | "max_steps" | "budget" | "cancelled" | "error"
    usage: Usage
    trace_id: str
