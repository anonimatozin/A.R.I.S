"""Dono: Parte 1 — clientes de LLM e roteador de modelos.

Camada única (``LLMRouter``, que implementa o ``LLMClient`` do contrato) por
trás de provedores OpenAI-compatíveis: Groq, OpenAI, OpenRouter, Ollama local.
"""

from __future__ import annotations

from .circuit import CircuitBreaker
from .limits import RateLimiter, RateLimits
from .provider import OpenAICompatProvider
from .router import LLMRouter, build_router
from .settings import LLMSettings, ProviderConfig, parse_settings
from .stats import UsageStats

__all__ = [
    "CircuitBreaker",
    "LLMRouter",
    "LLMSettings",
    "OpenAICompatProvider",
    "ProviderConfig",
    "RateLimits",
    "RateLimiter",
    "UsageStats",
    "build_router",
    "parse_settings",
]
