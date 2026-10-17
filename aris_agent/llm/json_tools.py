"""Emulação de tool calling via prompt (``tool_mode="json_prompt"``).

Modelos pequenos/locais sem suporte nativo a ferramentas recebem as ferramentas
dentro do prompt e devem responder apenas JSON:

    {"tool_call": {"name": "...", "arguments": {...}}}
    ou {"final": "resposta final"}

O parser é tolerante: remove cercas de código, acha o objeto JSON no meio do
texto e tenta reparos simples (aspas simples, vírgula final, chave sem aspas).
"""

from __future__ import annotations

import ast
import json
import logging
import re
import uuid
from dataclasses import dataclass, field

from ..contract.errors import ProviderError
from ..contract.types import ChatMessage, ToolCall, ToolSpec
from ..contract.utils import redact_secrets, truncate_text

log = logging.getLogger("aris.agent.llm.json_tools")

_FINAL_KEYS = ("final", "content", "text", "answer", "resposta")

_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_BARE_KEY_RE = re.compile(r"(?m)([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:")


def instruction_text(tools: list[ToolSpec]) -> str:
    """Bloco de instrução com as ferramentas e o formato JSON exigido."""
    described = [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        }
        for tool in tools
    ]
    listing = json.dumps(described, ensure_ascii=False, indent=2)
    return (
        "Você tem estas ferramentas disponíveis (use somente se precisar):\n"
        f"{listing}\n\n"
        "Responda SOMENTE com um destes objetos JSON, sem texto fora dele:\n"
        '{"tool_call": {"name": "<nome da ferramenta>", "arguments": {<argumentos>}}}\n'
        'ou {"final": "<sua resposta final em texto>"}'
    )


def with_instruction(messages: list[ChatMessage], tools: list[ToolSpec]) -> list[ChatMessage]:
    """Copia a conversa com a instrução de ferramentas inserida após o system."""
    instruction = ChatMessage(role="system", content=instruction_text(tools))
    index = 0
    while index < len(messages) and messages[index].role == "system":
        index += 1
    return [*messages[:index], instruction, *messages[index:]]


@dataclass
class Envelope:
    """Resultado de ``parse_envelope``."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _find_balanced(text: str) -> str | None:
    """Primeiro objeto JSON balanceado do texto (respeitando strings/escapes)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        quote = ""
        for position in range(start, len(text)):
            char = text[position]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = in_string
                continue
            if in_string:
                if char == quote:
                    in_string = False
                continue
            if char in "\"'":
                in_string = True
                quote = char
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : position + 1]
        start = text.find("{", start + 1)
    return None


def _repair(text: str) -> str:
    fixed = (
        text.replace("‘", '"')
        .replace("’", '"')
        .replace("“", '"')
        .replace("”", '"')
    )
    fixed = _TRAILING_COMMA_RE.sub(r"\1", fixed)
    fixed = _BARE_KEY_RE.sub(r'\1"\2":', fixed)
    return fixed


def _loads_tolerant(text: str) -> object:
    """JSON estrito → ``ast.literal_eval`` → reparos simples."""
    attempts = [text, _repair(text)]
    errors: list[str] = []
    for attempt in attempts:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
        try:
            value = ast.literal_eval(attempt)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
            try:
                return json.loads(json.dumps(value, ensure_ascii=False))
            except (TypeError, ValueError):  # pragma: no cover - defensivo
                continue
    log.debug("JSON não parseou: %s", errors[-1] if errors else "?")
    return None


def _tool_format_error(message: str) -> ProviderError:
    return ProviderError(f"resposta em JSON de ferramenta inválida: {message}", kind="tool_format")


def _coerce_arguments(raw: object, name: str) -> dict:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        parsed = _loads_tolerant(raw)
        if isinstance(parsed, dict):
            return parsed
        raise _tool_format_error(f"argumentos de {name!r} não são JSON válido")
    raise _tool_format_error(f"argumentos de {name!r} têm tipo {type(raw).__name__}")


def _call_from(raw: object) -> ToolCall:
    if not isinstance(raw, dict):
        raise _tool_format_error(f"chamada de ferramenta não é objeto: {type(raw).__name__}")
    if isinstance(raw.get("function"), dict):
        raw = {**raw, **raw["function"]}
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _tool_format_error("chamada de ferramenta sem nome")
    arguments = _coerce_arguments(raw.get("arguments", raw.get("args")), name.strip())
    call_id = raw.get("id")
    if not isinstance(call_id, str) or not call_id:
        call_id = f"call_{uuid.uuid4().hex[:12]}"
    return ToolCall(id=call_id, name=name.strip(), arguments=arguments)


def parse_envelope(text: str, *, tools: list[ToolSpec] | None = None) -> Envelope:
    """Converte a resposta do modelo no envelope ``tool_call``/``final``.

    Levanta ``ProviderError(kind="tool_format")`` se nada aproveitável sair.
    """
    snippet = truncate_text(redact_secrets(str(text or "")), 300)
    if not text or not text.strip():
        raise _tool_format_error("resposta vazia")

    stripped = _strip_fences(text)
    data: object = None
    candidates = [c for c in (_find_balanced(stripped), stripped) if c]
    for candidate in candidates:
        data = _loads_tolerant(candidate)
        if isinstance(data, dict):
            break
    if data is None:
        raise _tool_format_error(f"não é JSON ({snippet})")
    if not isinstance(data, dict):
        raise _tool_format_error(f"esperado objeto JSON, veio {type(data).__name__} ({snippet})")

    raw_calls: list = []
    if isinstance(data.get("tool_call"), dict):
        raw_calls = [data["tool_call"]]
    elif isinstance(data.get("tool_calls"), list):
        raw_calls = list(data["tool_calls"])
    elif isinstance(data.get("name"), str) and tools is not None:
        raw_calls = [data]

    if raw_calls:
        content = ""
        for key in ("content", "text"):
            if isinstance(data.get(key), str):
                content = data[key]
                break
        calls = [_call_from(raw) for raw in raw_calls]
        return Envelope(content=content, tool_calls=calls)

    for key in _FINAL_KEYS:
        if key in data and data[key] is not None:
            value = data[key]
            final = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            return Envelope(content=final)

    raise _tool_format_error(f"JSON sem 'tool_call' nem 'final' ({snippet})")
