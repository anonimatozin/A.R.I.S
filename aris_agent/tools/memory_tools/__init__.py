"""Ferramentas de memória da A.R.I.S. (Parte 4).

A instância de memória entra por um ponto de injeção simples::

    from aris_agent.tools.memory_tools import set_memory
    from aris_agent.memory import SqliteMemory

    set_memory(SqliteMemory(caminho))   # chamado pela Parte 8

Sem memória configurada, as ferramentas devolvem ``ToolResult(ok=False)`` com
mensagem clara — nada de exceção para o laço do agente.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ...memory.textutil import clean_tags
from ..registry import ToolRegistry, function_tool

if TYPE_CHECKING:
    from ...contract.protocols import Memory

log = logging.getLogger("aris.agent.tools.memory_tools")

__all__ = ["get_memory", "register", "set_memory"]

_lock = threading.Lock()
_memory: Memory | None = None

_REMEMBER_SPEC = ToolSpec(
    name="memory_remember",
    description=(
        "Guarda informação DURÁVEL na memória de longo prazo da A.R.I.S. Use apenas para: "
        "fatos sobre o usuário ou o mundo dele (kind='fact'); preferências dele "
        "(kind='preference'); lições aprendidas quando o usuário te corrigir — no padrão "
        "'quando X, fazer Y / não fazer Z' (kind='lesson'); e resumos de algo que aconteceu "
        "(kind='episode'). NÃO guarde conversa descartável, dados temporários, texto da web "
        "inteiro, nem chaves/senhas/token. Sempre que o usuário te corrigir ou ensinar um "
        "jeito melhor de fazer algo, registre uma lesson na hora."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "conteúdo a guardar, em português e autossuficiente (entenda-se sozinho, sem depender do resto da conversa)",
            },
            "kind": {
                "type": "string",
                "enum": ["fact", "preference", "lesson", "episode"],
                "default": "fact",
                "description": "categoria: fact | preference | lesson | episode",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "tags curtas para agrupar (ex.: ['casa', 'projeto'])",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
    risk=Risk.WRITE,
    tags=("memory",),
)

_RECALL_SPEC = ToolSpec(
    name="memory_recall",
    description=(
        "Recupera da memória de longo prazo os itens mais relevantes para uma pergunta "
        "(a busca ignora acento e caixa). Use antes de responder sobre o usuário, as "
        "preferências dele, decisões anteriores ou lições; cada item volta com score de "
        "0 a 1 (quanto maior, mais relevante)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "pergunta ou termos a buscar na memória",
            },
            "k": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
                "description": "quantidade máxima de itens (padrão 5)",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    risk=Risk.READ,
    untrusted_output=True,  # texto guardado antes pode ter vindo da web/arquivos
    tags=("memory",),
)

_FORGET_SPEC = ToolSpec(
    name="memory_forget",
    description=(
        "Apaga UM item da memória de longo prazo pelo id (use somente quando o usuário "
        "pedir para esquecer algo específico; não apaga a conversa)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "id do item, como retornado por memory_recall/memory_remember",
            },
        },
        "required": ["id"],
        "additionalProperties": False,
    },
    risk=Risk.WRITE,
    untrusted_output=False,
    tags=("memory",),
)


def set_memory(memory: Memory | None) -> None:
    """Ponto de injeção: liga/desliga a memória usada pelas ferramentas."""
    global _memory
    with _lock:
        _memory = memory
    log.info(
        "memória %s configurada nas ferramentas",
        type(memory).__name__ if memory is not None else "nenhuma",
    )


def get_memory() -> Memory | None:
    """Memória configurada (``None`` = ferramentas respondem ``ok=False``)."""
    with _lock:
        return _memory


def _no_memory() -> ToolResult:
    return ToolResult(
        ok=False,
        error=(
            "memória não configurada: chame set_memory(memory) em "
            "aris_agent.tools.memory_tools com uma instância de SqliteMemory"
        ),
    )


def _tags_of(raw: object) -> tuple[str, ...]:
    """Aceita lista ou string separada por vírgulas (LLM erra menos quebrando)."""
    if isinstance(raw, str | list | tuple):
        return clean_tags(raw)
    return ()


@function_tool(_REMEMBER_SPEC)
def _remember(args: dict, ctx: ToolContext) -> ToolResult:
    memory = get_memory()
    if memory is None:
        return _no_memory()
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        return ToolResult(ok=False, error="parâmetro 'text' obrigatório e não vazio")
    kind = args.get("kind") or "fact"
    tags = _tags_of(args.get("tags"))
    try:
        item_id = memory.remember(text, kind=kind, tags=tags)
    except (TypeError, ValueError) as exc:
        return ToolResult(ok=False, error=f"não guardei na memória: {exc}")
    return ToolResult(
        ok=True,
        content=f"guardado na memória (id={item_id}, kind={kind})",
        data={"id": item_id, "kind": kind, "tags": list(tags)},
    )


@function_tool(_RECALL_SPEC)
def _recall(args: dict, ctx: ToolContext) -> ToolResult:
    memory = get_memory()
    if memory is None:
        return _no_memory()
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolResult(ok=False, error="parâmetro 'query' obrigatório e não vazio")
    raw_k = args.get("k", 5)
    try:
        k = int(raw_k)
    except (TypeError, ValueError):
        k = 5
    k = max(1, min(20, k))
    items = memory.recall(query, k)
    if not items:
        content = "nenhuma memória relevante para esta consulta."
    else:
        linhas = [
            f"- [{item.kind}] score={item.score:.2f} id={item.id} :: {item.text}"
            for item in items
        ]
        content = "memórias relevantes:\n" + "\n".join(linhas)
    data = [
        {
            "id": item.id,
            "kind": item.kind,
            "score": item.score,
            "tags": list(item.tags),
            "created_at": item.created_at,
        }
        for item in items
    ]
    return ToolResult(ok=True, content=content, data=data)


@function_tool(_FORGET_SPEC)
def _forget(args: dict, ctx: ToolContext) -> ToolResult:
    memory = get_memory()
    if memory is None:
        return _no_memory()
    item_id = args.get("id")
    if not isinstance(item_id, str) or not item_id.strip():
        return ToolResult(ok=False, error="parâmetro 'id' obrigatório e não vazio")
    item_id = item_id.strip()
    if not memory.forget(item_id):
        return ToolResult(ok=False, error=f"memória {item_id} não encontrada")
    return ToolResult(ok=True, content=f"esquecido: {item_id}", data={"id": item_id})


def register(registry: ToolRegistry) -> None:
    """Registra as três ferramentas de memória (idempotente)."""
    for tool in (_remember, _recall, _forget):
        if tool.spec.name not in registry:
            registry.register(tool)
    log.debug("ferramentas de memória registradas")
