"""Provedor genérico para APIs no formato ``/v1/chat/completions``.

Cobre Groq, OpenAI, OpenRouter, Ollama (``/v1``), Gemini em modo compatível etc.
Sem SDK de provedor: só ``httpx``. Retry com backoff exponencial + jitter em
429/5xx/timeout respeitando ``Retry-After``; erro 400 de tool malformada do
estilo Groq (``failed_generation`` / ``tool_use_failed``) ganha **uma** nova
tentativa com temperatura reduzida antes de falhar.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from ..contract.errors import ProviderError
from ..contract.types import ChatMessage, LLMResponse, ToolCall, ToolSpec, Usage
from ..contract.utils import redact_secrets, truncate_text
from .json_tools import parse_envelope, with_instruction
from .settings import ProviderConfig

log = logging.getLogger("aris.agent.llm.provider")

_RETRYABLE_KINDS = frozenset({"rate_limit", "server", "network"})

# Marcadores do erro 400 "tool use failed" documentado pela Groq
# (campo ``failed_generation`` e/ou code ``tool_use_failed`` na resposta).
_TOOL_GENERATION_CODES = frozenset({"tool_use_failed", "failed_generation"})
_TOOL_GENERATION_MESSAGES = (
    "failed_generation",
    "tool call validation failed",
    "invalid tool call",
    "failed to generate a valid tool call",
    "tool use failed",
)


def message_to_dict(message: ChatMessage) -> dict:
    """Converte ``ChatMessage`` do contrato para o formato da API."""
    data: dict = {"role": message.role, "content": message.content or ""}
    if message.role == "assistant" and message.tool_calls:
        data["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments or {}, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    if message.role == "tool":
        if message.tool_call_id:
            data["tool_call_id"] = message.tool_call_id
        if message.name:
            data["name"] = message.name
    return data


def tools_to_dict(tools: list[ToolSpec]) -> list[dict]:
    """Converte ``ToolSpec`` do contrato para o formato ``tools`` da API."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


class OpenAICompatProvider:
    """Cliente HTTP de um provedor OpenAI-compatível."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        env: dict | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self._owns_client = client is None
        self._sleeper = sleeper
        self._clock = clock
        self._rng = rng or random.Random()
        self._env = env if env is not None else os.environ
        self._url = f"{config.base_url.rstrip('/')}/chat/completions"

    # ---- estado -----------------------------------------------------------

    @property
    def name(self) -> str:
        return self.config.name

    def api_key(self) -> str | None:
        """Chave lida da variável de ambiente configurada (``None`` se local)."""
        if not self.config.api_key_env:
            return None
        value = str(self._env.get(self.config.api_key_env) or "").strip()
        return value or None

    @property
    def enabled(self) -> bool:
        """Falso quando a chave esperada não existe: provedor desativado (aviso)."""
        return self.status() is None

    def status(self) -> str | None:
        """Motivo da desativação, ou ``None`` se o provedor está utilizável."""
        if not self.config.enabled:
            return "desativado na configuração (enabled=false)"
        if self.config.api_key_env and self.api_key() is None:
            return f"variável {self.config.api_key_env} ausente ou vazia"
        if not self.config.models:
            return "nenhum modelo configurado (chave models)"
        return None

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"<OpenAICompatProvider {self.config.name} ativo={self.enabled}>"

    # ---- chamada ----------------------------------------------------------

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        *,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Uma requisição (com retries) → ``LLMResponse``."""
        reason = self.status()
        if reason is not None:
            log.warning("provedor %s desativado: %s", self.name, reason)
            raise ProviderError(f"provedor {self.name} desativado: {reason}", kind="auth")

        target = model or self.config.models[0]
        payload = self._build_payload(messages, tools, target, max_tokens, temperature)

        attempt = 0
        tool_attempts = 0
        while True:
            attempt += 1
            try:
                data = self._post(payload, target, attempt)
                return self._to_response(data, target, tools)
            except ProviderError as exc:
                message = redact_secrets(str(exc))
                if exc.kind == "tool_format" and tool_attempts < 1 and attempt < self.config.max_attempts:
                    tool_attempts += 1
                    lowered = max(float(payload["temperature"]) - 0.2, 0.0)
                    payload["temperature"] = lowered
                    log.warning(
                        "provedor %s: ferramenta malformada; nova tentativa com temperatura %.2f",
                        self.name,
                        lowered,
                    )
                    continue
                if exc.kind in _RETRYABLE_KINDS and attempt < self.config.max_attempts:
                    delay = self._delay(attempt, exc.retry_after_s)
                    log.info(
                        "provedor %s: %s (tentativa %d/%d) — aguardando %.1fs",
                        self.name,
                        message,
                        attempt,
                        self.config.max_attempts,
                        delay,
                    )
                    self._sleeper(delay)
                    continue
                raise

    def _build_payload(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> dict:
        outgoing = list(messages)
        payload: dict = {
            "model": model,
            "messages": [],
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
        }
        if tools:
            if self.config.tool_mode == "json_prompt":
                outgoing = with_instruction(outgoing, tools)
            else:
                payload["tools"] = tools_to_dict(tools)
                payload["tool_choice"] = "auto"
        payload["messages"] = [message_to_dict(message) for message in outgoing]
        return payload

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(follow_redirects=False)
        return self._client

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        key = self.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _post(self, payload: dict, model: str, attempt: int) -> dict:
        """Envia a requisição e devolve o corpo JSON de sucesso (ou levanta)."""
        started = self._clock()
        log.debug(
            "POST %s provedor=%s modelo=%s tentativa=%d",
            self._url,
            self.name,
            model,
            attempt,
        )
        try:
            response = self._http().post(
                self._url,
                json=payload,
                headers=self._headers(),
                timeout=self.config.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"provedor {self.name}: timeout após {self.config.timeout_s:.0f}s ({exc})",
                kind="network",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"provedor {self.name}: falha de rede ({type(exc).__name__})",
                kind="network",
            ) from exc

        log.debug(
            "resposta %s em %.2fs (%d bytes)",
            response.status_code,
            self._clock() - started,
            len(response.content),
        )
        if response.status_code >= 400:
            kind, retry_after, message = self._classify_error(response)
            summary = redact_secrets(truncate_text(message, 400))
            log.warning(
                "provedor %s: HTTP %d — %s", self.name, response.status_code, summary
            )
            raise ProviderError(
                f"provedor {self.name}: HTTP {response.status_code}: {summary}",
                kind=kind,
                retry_after_s=retry_after,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"provedor {self.name}: corpo da resposta não é JSON", kind="server"
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                f"provedor {self.name}: resposta JSON inesperada ({type(data).__name__})",
                kind="server",
            )
        return data

    def _classify_error(self, response: httpx.Response) -> tuple[str, float | None, str]:
        """HTTP ≥400 → (kind, retry_after_s, mensagem)."""
        status = response.status_code
        message, code, has_failed_generation = _error_details(response)
        if status in (400, 422):
            lower = message.lower()
            if (
                code in _TOOL_GENERATION_CODES
                or has_failed_generation
                or any(marker in lower for marker in _TOOL_GENERATION_MESSAGES)
            ):
                return "tool_format", None, message
            return "bad_request", None, message
        if status in (401, 403):
            return "auth", None, message
        if status == 429:
            return "rate_limit", _retry_after(response), message
        if status == 408:
            return "network", None, message
        if status >= 500:
            return "server", _retry_after(response), message
        return "bad_request", None, message

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(max(0.0, retry_after), self.config.max_backoff_s)
        base = self.config.backoff_base_s * (2 ** max(0, attempt - 1))
        jitter = self._rng.uniform(0.0, base) if base > 0 else 0.0
        return min(base + jitter, self.config.max_backoff_s)

    # ---- resposta ---------------------------------------------------------

    def _to_response(
        self, data: dict, model: str, tools: list[ToolSpec] | None
    ) -> LLMResponse:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError(
                f"provedor {self.name}: resposta sem choices", kind="server"
            )
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message_raw = choice.get("message") or {}
        content = message_raw.get("content") or ""
        raw_calls = message_raw.get("tool_calls") or []

        tool_calls: list[ToolCall] = []
        if isinstance(raw_calls, list):
            tool_calls = [self._parse_tool_call(item) for item in raw_calls]

        finish = str(choice.get("finish_reason") or "") or (
            "tool_calls" if tool_calls else "stop"
        )

        if not tool_calls and self.config.tool_mode == "json_prompt":
            envelope = parse_envelope(content, tools=tools)
            return LLMResponse(
                message=ChatMessage(
                    role="assistant",
                    content=envelope.content,
                    tool_calls=envelope.tool_calls or None,
                ),
                usage=_usage_from(data),
                provider=self.name,
                model=str(data.get("model") or model),
                finish_reason="tool_calls" if envelope.tool_calls else "stop",
            )

        return LLMResponse(
            message=ChatMessage(
                role="assistant",
                content=str(content),
                tool_calls=tool_calls or None,
            ),
            usage=_usage_from(data),
            provider=self.name,
            model=str(data.get("model") or model),
            finish_reason=finish,
        )

    def _parse_tool_call(self, raw: object) -> ToolCall:
        if not isinstance(raw, dict):
            raise _tool_format(f"tool_call com tipo {type(raw).__name__}")
        function = raw.get("function")
        if isinstance(function, dict):
            raw = {**raw, **function}
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _tool_format("tool_call sem nome de função")
        arguments_raw = raw.get("arguments", "{}")
        if isinstance(arguments_raw, dict):
            arguments = dict(arguments_raw)
        elif arguments_raw is None or arguments_raw == "":
            arguments = {}
        elif isinstance(arguments_raw, str):
            try:
                parsed = json.loads(arguments_raw)
            except json.JSONDecodeError as exc:
                raise _tool_format(
                    f"argumentos de {name.strip()!r} não são JSON válido: {exc.msg}"
                ) from exc
            if not isinstance(parsed, dict):
                raise _tool_format(
                    f"argumentos de {name.strip()!r} não são um objeto JSON"
                )
            arguments = parsed
        else:
            raise _tool_format(
                f"argumentos de {name.strip()!r} têm tipo {type(arguments_raw).__name__}"
            )
        call_id = raw.get("id")
        if not isinstance(call_id, str) or not call_id:
            call_id = f"call_{uuid.uuid4().hex[:12]}"
        return ToolCall(id=call_id, name=name.strip(), arguments=arguments)


def _tool_format(message: str) -> ProviderError:
    return ProviderError(
        f"tool_format: {message}", kind="tool_format"
    )


def _error_details(response: httpx.Response) -> tuple[str, str | None, bool]:
    """Mensagem/code do corpo de erro (formato OpenAI/Groq), sem segredos."""
    message = ""
    code: str | None = None
    has_failed_generation = False
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "")
            raw_code = error.get("code")
            code = str(raw_code) if raw_code else None
            has_failed_generation = "failed_generation" in error
        elif isinstance(error, str):
            message = error
        elif body.get("failed_generation") is not None:
            has_failed_generation = True
            message = str(body.get("message") or "")
    if not message:
        message = truncate_text(response.text or f"HTTP {response.status_code}", 400)
    return message, code, has_failed_generation


def _retry_after(response: httpx.Response) -> float | None:
    """Header ``Retry-After`` em segundos (número ou data HTTP)."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(raw)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return max(0.0, (moment - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):  # pragma: no cover - formatação estranha
        return None


def _usage_from(data: dict) -> Usage:
    raw = data.get("usage")
    if not isinstance(raw, dict):
        return Usage()
    try:
        return Usage(
            prompt_tokens=int(raw.get("prompt_tokens") or 0),
            completion_tokens=int(raw.get("completion_tokens") or 0),
        )
    except (TypeError, ValueError):  # pragma: no cover - corpo malformado
        return Usage()
