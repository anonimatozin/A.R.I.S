"""Router genérico de provedores LLM com capability routing e failover.

Provider unificado que suporta qualquer API compatível com OpenAI
(Groq, Gemini, Ollama, OpenAI direto, etc). Fallback automático
entre provedores com rate limiting e circuit breaker por provider.

Variáveis de ambiente suportadas (auto-detected):
    GROQ_API_KEY, GEMINI_API_KEY         → providers automáticos
    ARIS_LLM_PRIMARY_MODEL               → modelo primário
    ARIS_LLM_{N}_NAME, _API_KEY, _MODEL, _BASE_URL, _CAPABILITIES
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from core.rate_limiter import gemini_limiter, groq_limiter, ollama_limiter
from utils.logger import Logger


class AllProvidersFailedError(Exception):
    """Lançada quando todos os providers falham em uma chamada LLM."""


@dataclass
class ProviderConfig:
    """Configuração de um provider LLM."""

    name: str
    api_key: str
    model: str
    base_url: str = ""
    capabilities: tuple[str, ...] = ("text",)
    rate_limiter: Any = None

    @property
    def supports_vision(self) -> bool:
        return "vision" in self.capabilities

    @property
    def supports_text(self) -> bool:
        return "text" in self.capabilities


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def parse_providers_from_env(
    logger: Logger | None = None,
) -> list[ProviderConfig]:
    """Lê variáveis de ambiente e monta a lista de providers.

    Suporta dois modos:
      1. Auto-detect: GROQ_API_KEY / GEMINI_API_KEY / Ollama local
      2. Explícito: ARIS_LLM_{N}_NAME, ARIS_LLM_{N}_API_KEY, etc.

    Retorna lista ordenada por prioridade (primário primeiro).
    """
    providers: list[ProviderConfig] = []
    seen_names: set[str] = set()

    # Modo 1: auto-detect a partir de chaves conhecidas
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        model = os.getenv("ARIS_CHAT_MODEL", "openai/gpt-oss-120b")
        providers.append(ProviderConfig(
            name="groq",
            api_key=groq_key,
            model=model,
            base_url="https://api.groq.com/openai/v1",
            capabilities=("text",),
            rate_limiter=groq_limiter,
        ))
        seen_names.add("groq")
        if logger:
            logger.info(f"LLM provider auto-detectado: groq ({model})")

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        providers.append(ProviderConfig(
            name="gemini",
            api_key=gemini_key,
            model=model,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            capabilities=("text", "vision"),
            rate_limiter=gemini_limiter,
        ))
        seen_names.add("gemini")
        if logger:
            logger.info(f"LLM provider auto-detectado: gemini ({model})")

    # Ollama local (sempre disponível como último fallback)
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2")
    providers.append(ProviderConfig(
        name="ollama",
        api_key="ollama",
        model=ollama_model,
        base_url=ollama_url,
        capabilities=("text", "vision"),
        rate_limiter=ollama_limiter,
    ))

    # Modo 2: providers explícitos via ARIS_LLM_{N}_*
    numbered = _parse_numbered_providers(seen_names, logger)
    if numbered:
        # Inserir explícitos ANTES do Ollama (que é fallback local)
        ollama_idx = next(
            (i for i, p in enumerate(providers) if p.name == "ollama"),
            len(providers),
        )
        for p in reversed(numbered):
            providers.insert(ollama_idx, p)

    if logger:
        names = [f"{p.name}({p.model})" for p in providers]
        logger.info(f"LLM providers carregados: {', '.join(names)}")

    return providers


def _parse_numbered_providers(
    existing_names: set[str],
    logger: Logger | None = None,
) -> list[ProviderConfig]:
    """Lê ARIS_LLM_{N}_* para providers explícitos (N=1..10)."""
    providers: list[ProviderConfig] = []
    pattern = re.compile(r"^ARIS_LLM_(\d+)_(.+)$")

    env_groups: dict[int, dict[str, str]] = {}
    for key, value in os.environ.items():
        m = pattern.match(key)
        if m:
            num = int(m.group(1))
            field_name = m.group(2).upper()
            env_groups.setdefault(num, {})[field_name] = value.strip()

    for num in sorted(env_groups):
        fields = env_groups[num]
        name = fields.get("NAME", f"custom_{num}").lower()
        if name in existing_names:
            if logger:
                logger.warning(f"Provider LLM#{num} '{name}' duplicado — ignorado")
            continue
        api_key = fields.get("API_KEY", "")
        model = fields.get("MODEL", "")
        base_url = fields.get("BASE_URL", "")
        caps_raw = fields.get("CAPABILITIES", "text")
        capabilities = tuple(c.strip().lower() for c in caps_raw.split(",") if c.strip())

        if not api_key or not model:
            if logger:
                logger.warning(f"Provider LLM#{num} '{name}' sem API_KEY ou MODEL — ignorado")
            continue

        # Rate limiter por nome conhecido
        limiter = None
        if name == "groq":
            limiter = groq_limiter
        elif name == "gemini":
            limiter = gemini_limiter
        elif name == "ollama":
            limiter = ollama_limiter

        providers.append(ProviderConfig(
            name=name,
            api_key=api_key,
            model=model,
            base_url=base_url,
            capabilities=capabilities,
            rate_limiter=limiter,
        ))
        existing_names.add(name)
        if logger:
            logger.info(f"Provider LLM explícito: {name} ({model}) caps={capabilities}")

    return providers


class LLMRouter:
    """Router unificado de provedores LLM com capability routing e failover.

    Uso:
        router = LLMRouter()
        reply = router.send("Olá, como vai?")
        # Com capability check:
        reply = router.send("Descreva esta imagem", capabilities=["vision"])
    """

    def __init__(
        self,
        providers: list[ProviderConfig] | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._logger = logger
        self._providers = providers if providers is not None else parse_providers_from_env(logger)
        self._clients: dict[str, OpenAI] = {}
        self._available: dict[str, bool] = {p.name: True for p in self._providers}

    @property
    def available(self) -> bool:
        """Pelo menos um provider está configurado e funcional."""
        return any(self._available.get(p.name, False) for p in self._providers)

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    def _get_client(self, provider: ProviderConfig) -> OpenAI | None:
        """Retorna (ou cria) o OpenAI client para um provider."""
        if provider.name in self._clients:
            return self._clients[provider.name]

        # Ollama: testar disponibilidade antes de criar client
        if provider.name == "ollama":
            try:
                client = OpenAI(api_key="ollama", base_url=provider.base_url)
                client.models.list()
            except Exception:
                if self._logger:
                    self._logger.debug(f"Ollama indisponível ({provider.base_url})")
                self._available[provider.name] = False
                return None
            self._clients[provider.name] = client
            return client

        try:
            client = OpenAI(
                api_key=provider.api_key,
                base_url=provider.base_url,
                timeout=30.0,
            )
            self._clients[provider.name] = client
            return client
        except Exception as exc:
            if self._logger:
                self._logger.warning(f"Falha ao criar client {provider.name}: {exc}")
            self._available[provider.name] = False
            return None

    def _supports_capability(
        self, provider: ProviderConfig, capability: str | None
    ) -> bool:
        if capability is None:
            return True
        return capability in provider.capabilities

    def send(
        self,
        message: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        capabilities: list[str] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> str:
        """Envia mensagem com fallback automático entre providers.

        Args:
            message: Mensagem do usuário (usada se messages não for fornecido).
            temperature: Temperatura de geração.
            max_tokens: Máximo de tokens na resposta.
            capabilities: Lista de capacidades exigidas (ex: ["vision"]).
            messages: Lista de mensagens completa (substitui message).

        Returns:
            Resposta do provedor.

        Raises:
            AllProvidersFailedError: Se nenhum provider funcionar.
        """
        if not self._providers:
            raise AllProvidersFailedError(
                "Nenhum provider LLM configurado. "
                "Defina GROQ_API_KEY ou GEMINI_API_KEY no .env."
            )

        # Reset circuit breaker para retry
        for p in self._providers:
            self._available[p.name] = True

        # Construir lista de mensagens
        if messages is not None:
            final_messages = messages
        else:
            final_messages = [{"role": "user", "content": message}]

        # Determinar quais capabilities são obrigatórias
        required_caps = set(capabilities) if capabilities else set()

        last_error: Exception | None = None
        for provider in self._providers:
            if not self._available.get(provider.name, False):
                continue

            # Capability check
            if required_caps and not all(
                self._supports_capability(provider, c) for c in required_caps
            ):
                if self._logger:
                    self._logger.debug(
                        f"Provider {provider.name} não suporta "
                        f"capabilities {required_caps} — pulando"
                    )
                continue

            # Rate limit check
            if provider.rate_limiter is not None:
                if not provider.rate_limiter.allow():
                    if self._logger:
                        limiter = provider.rate_limiter
                        self._logger.warning(
                            f"Rate limit {provider.name} "
                            f"({limiter.remaining}/{limiter.max_calls})"
                        )
                    continue
            # Se rate_limiter é None, este provider não tem limite configurado
            # — comportamento aceitável (provider local/sem quota)

            # Obter client
            client = self._get_client(provider)
            if client is None:
                continue

            try:
                response = client.chat.completions.create(
                    model=provider.model,
                    messages=final_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                reply = response.choices[0].message.content.strip()

                if self._logger:
                    self._logger.debug(
                        f"LLM [{provider.name}]: {reply[:120]}..."
                    )

                return reply

            except Exception as exc:
                last_error = exc
                self._available[provider.name] = False
                if self._logger:
                    self._logger.warning(f"Provider {provider.name} falhou: {exc}")
                continue

        # Todos falharam
        if last_error is None:
            msg = "Nenhum provider LLM disponível. Verifique as chaves no .env."
        else:
            msg = f"Todos os providers LLM falharam. Último erro: {last_error}"

        if self._logger:
            self._logger.error(msg)

        raise AllProvidersFailedError(msg)

    def get_status(self) -> dict[str, Any]:
        """Retorna status de todos os providers."""
        return {
            "providers": [
                {
                    "name": p.name,
                    "model": p.model,
                    "available": self._available.get(p.name, False),
                    "capabilities": list(p.capabilities),
                }
                for p in self._providers
            ],
        }

    def clear_clients(self) -> None:
        """Remove todos os clientes cached (força re-conexão)."""
        self._clients.clear()
