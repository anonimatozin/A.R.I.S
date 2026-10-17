"""Roteador de modelos: implementa o ``LLMClient`` do contrato.

``difficulty`` (easy/normal/hard) escolhe uma cadeia ``provedor:modelo`` vinda
da seção ``llm`` da configuração. Percorre a cadeia até uma resposta válida,
pulando provedor desativado, com circuito aberto ou sem orçamento (aí prefere
o próximo provedor; só espera quando não há alternativa e a espera é curta).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from ..config import AgentConfig, load_config
from ..contract.errors import ProviderError
from ..contract.types import ChatMessage, LLMResponse, ToolSpec
from ..contract.utils import redact_secrets
from .circuit import CircuitBreaker
from .limits import RateLimiter
from .provider import OpenAICompatProvider
from .settings import LLMSettings, parse_settings
from .stats import UsageStats

log = logging.getLogger("aris.agent.llm.router")


def estimate_request_tokens(
    messages: list[ChatMessage], tools: list[ToolSpec] | None, max_tokens: int
) -> int:
    """Estimativa conservadora (≈4 caracteres por token) para o pré-check."""
    chars = 0
    for message in messages:
        chars += len(message.content or "")
        if message.tool_calls:
            chars += 40 * len(message.tool_calls)
    if tools:
        for tool in tools:
            chars += len(tool.name) + len(tool.description)
            chars += len(json.dumps(tool.parameters or {}, ensure_ascii=False))
    return chars // 4 + max(0, int(max_tokens))


class LLMRouter:
    """Escolhe provedor:modelo por dificuldade, com fallback e contabilidade."""

    def __init__(
        self,
        settings: LLMSettings,
        *,
        providers: dict | None = None,
        data_dir: Path | str | None = None,
        stats: UsageStats | None = None,
        limiter: RateLimiter | None = None,
        breaker: CircuitBreaker | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        if providers is None:
            providers = {
                cfg.name: OpenAICompatProvider(cfg) for cfg in settings.providers.values()
            }
        self.providers: dict = dict(providers)
        if stats is None:
            base = Path(data_dir) if data_dir is not None else Path.home() / ".aris_agent"
            stats = UsageStats(base / settings.stats_file, wall=wall)
        self.stats_store = stats
        self.stats_store.load()
        self.limiter = limiter or RateLimiter(clock=clock, wall=wall)
        for name, cfg in settings.providers.items():
            self.limiter.set_limits(name, cfg.limits)
        for name in self.providers:
            self.limiter.seed_day_tokens(name, self.stats_store.day_tokens(name))
        self.breaker = breaker or CircuitBreaker(
            clock=clock,
            failure_threshold=settings.failure_threshold,
            cooldown_s=settings.cooldown_s,
        )
        self._sleeper = sleeper
        self.last_used: tuple[str, str] | None = None

    # ---- protocolo LLMClient ---------------------------------------------

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        *,
        difficulty: str = "normal",
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> LLMResponse:
        chain = self.settings.chain_for(difficulty)
        if not chain:
            raise ProviderError(
                f"nenhuma cadeia de provedores para difficulty={difficulty!r}; "
                "configure a seção llm (providers + chains) no aris_agent.json",
                kind="bad_request",
            )

        estimated = estimate_request_tokens(messages, tools, max_tokens)
        failures: list[str] = []
        kinds: list[str] = []

        for index, (provider_name, model) in enumerate(chain):
            target = f"{provider_name}:{model}"
            provider = self.providers.get(provider_name)
            if provider is None:
                failures.append(f"{target}=desconhecido")
                log.warning("cadeia cita provedor desconhecido %r", provider_name)
                continue

            reason = provider.status() if hasattr(provider, "status") else None
            if reason is not None:
                failures.append(f"{target}=desativado")
                log.warning("pulando %s: %s", target, reason)
                continue

            wait = self.limiter.wait_time(provider_name, estimated)
            if wait > 0:
                if wait <= self.settings.max_wait_s and not self._has_alternative(
                    chain[index + 1 :]
                ):
                    log.info(
                        "orçamento de %s esgotado; aguardando %.1fs (sem alternativa)",
                        target,
                        wait,
                    )
                    self._sleeper(wait)
                else:
                    failures.append(f"{target}=rate_limit")
                    log.info("orçamento de %s esgotado; indo para o próximo", target)
                    continue

            if not self.breaker.allow(provider_name):
                failures.append(f"{target}=circuit_aberto")
                log.debug("circuit breaker aberto para %s; pulando", target)
                continue

            try:
                response = provider.chat(
                    messages,
                    tools,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except ProviderError as exc:
                self.breaker.failure(provider_name, immediate=(exc.kind == "auth"))
                kinds.append(exc.kind)
                failures.append(f"{target}={exc.kind}")
                log.warning(
                    "provedor %s falhou (%s): %s",
                    target,
                    exc.kind,
                    redact_secrets(str(exc)),
                )
                continue
            except Exception as exc:  # noqa: BLE001 - provedor não derruba o laço
                self.breaker.failure(provider_name)
                kinds.append("server")
                failures.append(f"{target}={type(exc).__name__}")
                log.exception("provedor %s lançou exceção inesperada", target)
                continue

            self._register_success(provider_name, response, model, difficulty)
            return response

        raise ProviderError(
            self._summary(difficulty, failures, kinds),
            kind=_dominant_kind(kinds),
        )

    # ---- apoio ------------------------------------------------------------

    def _has_alternative(self, rest: list[tuple[str, str]]) -> bool:
        for provider_name, _model in rest:
            provider = self.providers.get(provider_name)
            if provider is None:
                continue
            if hasattr(provider, "status") and provider.status() is not None:
                continue
            if self.limiter.wait_time(provider_name, 0) <= 0:
                return True
        return False

    def _register_success(
        self, provider_name: str, response: LLMResponse, model: str, difficulty: str
    ) -> None:
        self.breaker.success(provider_name)
        used = response.usage
        total = used.prompt_tokens + used.completion_tokens
        self.limiter.record_request(provider_name)
        if total:
            self.limiter.record_tokens(provider_name, total)
        self.stats_store.record(
            response.provider or provider_name, response.model or model, used
        )
        self.stats_store.save()
        self.last_used = (provider_name, response.model or model)
        log.info(
            "respondeu %s:%s (difficulty=%s, %d tokens: %d+%d)",
            provider_name,
            response.model or model,
            difficulty,
            total,
            used.prompt_tokens,
            used.completion_tokens,
        )

    @staticmethod
    def _summary(difficulty: str, failures: list[str], kinds: list[str]) -> str:
        detail = "; ".join(failures) or "nenhum provedor disponível"
        return f"todos os provedores falharam para difficulty={difficulty!r}: {detail}"

    # ---- inspeção ---------------------------------------------------------

    def stats(self) -> dict:
        """Uso, circuitos, limites e status dos provedores (JSON-safe)."""
        provider_status = {}
        for name, provider in sorted(self.providers.items()):
            reason = provider.status() if hasattr(provider, "status") else None
            config = getattr(provider, "config", None)
            provider_status[name] = {
                "ativo": reason is None,
                "motivo": reason,
                "modelos": list(config.models) if config is not None else [],
                "tool_mode": config.tool_mode if config is not None else None,
            }
        return {
            "usage": self.stats_store.snapshot(),
            "circuits": self.breaker.snapshot(),
            "limits": self.limiter.snapshot(),
            "providers": provider_status,
            "chains": {
                difficulty: [f"{name}:{model}" for name, model in entries]
                for difficulty, entries in self.settings.chains.items()
            },
            "last_used": list(self.last_used) if self.last_used else None,
        }

    def close(self) -> None:
        for provider in self.providers.values():
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"<LLMRouter {sorted(self.providers)}>"


def _dominant_kind(kinds: list[str]) -> str:
    unique = set(kinds)
    if len(unique) == 1:
        return next(iter(unique))
    return "server" if unique else "bad_request"


def build_router(cfg: AgentConfig | None = None) -> LLMRouter:
    """Monta o roteador a partir da seção ``llm`` da configuração."""
    config = cfg if cfg is not None else load_config()
    settings = parse_settings(config.section("llm"))
    return LLMRouter(settings, data_dir=config.data_dir)
