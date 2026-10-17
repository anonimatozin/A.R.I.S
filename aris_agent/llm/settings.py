"""Configuração da seção ``llm`` do ``aris_agent.json``.

Nada aqui fixa nome de modelo: provedores, modelos e cadeias vêm todos da
configuração. ``EXEMPLO_CADEIAS`` é somente um exemplo para o usuário copiar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("aris.agent.llm.settings")

DIFFICULTIES: tuple[str, ...] = ("easy", "normal", "hard")

# EXEMPLO — troque pelos modelos que você realmente tem em cada provedor.
# Estes nomes NÃO são usados pelo código; estão aqui só para copiar/colar.
EXEMPLO_CADEIAS: dict[str, list[str]] = {
    "easy": ["ollama:MODELO-LOCAL-PEQUENO", "groq:MODELO-PEQUENO"],
    "normal": ["groq:MODELO-MEDIO", "ollama:MODELO-LOCAL"],
    "hard": ["groq:MODELO-GRANDE", "ollama:MODELO-LOCAL"],
}

TOOL_MODES: tuple[str, ...] = ("native", "json_prompt")


@dataclass(frozen=True)
class RateLimits:
    """Orçamento de um provedor. ``None`` = sem limite naquele eixo."""

    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    tokens_per_day: int | None = None

    def has_limits(self) -> bool:
        return any(
            v is not None and v > 0
            for v in (
                self.requests_per_minute,
                self.tokens_per_minute,
                self.tokens_per_day,
            )
        )


@dataclass(frozen=True)
class ProviderConfig:
    """Um provedor OpenAI-compatível (Groq, OpenAI, OpenRouter, Ollama...)."""

    name: str
    base_url: str  # ex.: "https://api.groq.com/openai/v1"
    api_key_env: str | None = None  # None = não precisa de chave (local)
    models: tuple[str, ...] = ()
    tool_mode: str = "native"  # "native" | "json_prompt"
    timeout_s: float = 60.0
    max_attempts: int = 3
    backoff_base_s: float = 0.5
    max_backoff_s: float = 30.0
    limits: RateLimits = field(default_factory=RateLimits)
    enabled: bool = True


@dataclass(frozen=True)
class LLMSettings:
    """Seção ``llm`` já interpretada."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    chains: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    max_wait_s: float = 10.0
    failure_threshold: int = 3
    cooldown_s: float = 60.0
    stats_file: str = "llm_usage.json"

    def chain_for(self, difficulty: str) -> list[tuple[str, str]]:
        """Cadeia ``[(provedor, modelo), ...]`` para a dificuldade pedida.

        Se a dificuldade não tiver cadeia, cai para ``normal``; se não houver
        nenhuma cadeia configurada, monta uma implícita na ordem dos provedores.
        """
        if difficulty in self.chains and self.chains[difficulty]:
            return list(self.chains[difficulty])
        if difficulty not in DIFFICULTIES:
            log.warning("difficulty desconhecida %r; usando fallback", difficulty)
        for candidate in (difficulty, "normal", "easy", "hard"):
            if candidate in self.chains and self.chains[candidate]:
                log.warning("sem cadeia para %r; usando a cadeia %r", difficulty, candidate)
                return list(self.chains[candidate])
        if self.chains:
            first = next(iter(self.chains))
            log.warning("sem cadeia para %r; usando a primeira cadeia %r", difficulty, first)
            return list(self.chains[first])
        implicit = [
            (cfg.name, cfg.models[0])
            for cfg in self.providers.values()
            if cfg.enabled and cfg.models
        ]
        if implicit:
            log.warning(
                "nenhuma cadeia configurada (sections.llm.chains); "
                "usando a ordem dos provedores como cadeia implícita"
            )
        return implicit


def _num(value: object, default: float, *, integer: bool = True) -> float | int:
    """Converte número vindo do JSON, com aviso e volta ao padrão se der ruim."""
    try:
        return int(value) if integer else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning("valor numérico inválido %r; usando %r", value, default)
        return default


def _parse_limits(raw: object, provider: str) -> RateLimits:
    if not isinstance(raw, dict):
        if raw is not None:
            log.warning("limits do provedor %r não é objeto; ignorado", provider)
        return RateLimits()
    aliases = {
        "requests_per_minute": ("requests_per_minute", "rpm"),
        "tokens_per_minute": ("tokens_per_minute", "tpm"),
        "tokens_per_day": ("tokens_per_day", "tpd"),
    }
    values: dict[str, int | None] = {}
    for field_name, keys in aliases.items():
        found = None
        for key in keys:
            if key in raw:
                found = _int_or_none(raw[key], provider, key)
                break
        values[field_name] = found
    return RateLimits(**values)


def _int_or_none(value: object, provider: str, key: str) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        log.warning("limite %r do provedor %r inválido: %r (ignorado)", key, provider, value)
        return None
    if number <= 0:
        return None
    return number


def _parse_provider(name: str, raw: object) -> ProviderConfig | None:
    if not isinstance(raw, dict):
        log.warning("provedor %r não é objeto; ignorado", name)
        return None
    base_url = str(raw.get("base_url") or "").strip()
    if not base_url:
        log.warning("provedor %r sem base_url; ignorado", name)
        return None
    models_raw = raw.get("models")
    if models_raw is None and raw.get("model"):
        models_raw = [raw["model"]]
    if isinstance(models_raw, str):
        models_raw = [models_raw]
    if not isinstance(models_raw, list):
        models_raw = []
    models = tuple(str(m).strip() for m in models_raw if str(m).strip())
    if not models:
        log.warning("provedor %r sem modelos (chave models); chamadas falharão", name)

    tool_mode = str(raw.get("tool_mode") or "native").strip().lower()
    if tool_mode not in TOOL_MODES:
        log.warning(
            "tool_mode %r do provedor %r desconhecido; usando native", tool_mode, name
        )
        tool_mode = "native"

    api_key_env = raw.get("api_key_env")
    api_key_env = str(api_key_env).strip() if api_key_env else None

    return ProviderConfig(
        name=name,
        base_url=base_url.rstrip("/"),
        api_key_env=api_key_env,
        models=models,
        tool_mode=tool_mode,
        timeout_s=float(_num(raw.get("timeout_s", 60.0), 60.0, integer=False)),
        max_attempts=max(1, int(_num(raw.get("max_attempts", 3), 3))),
        backoff_base_s=float(_num(raw.get("backoff_base_s", 0.5), 0.5, integer=False)),
        max_backoff_s=float(_num(raw.get("max_backoff_s", 30.0), 30.0, integer=False)),
        limits=_parse_limits(raw.get("limits"), name),
        enabled=bool(raw.get("enabled", True)),
    )


def parse_target(target: str) -> tuple[str, str] | None:
    """``"provedor:modelo"`` → ``(provedor, modelo)``. Modelo pode conter ``:``."""
    text = str(target or "").strip()
    if ":" not in text:
        log.warning("entrada de cadeia inválida %r (esperado provedor:modelo)", target)
        return None
    provider, model = text.split(":", 1)
    provider, model = provider.strip(), model.strip()
    if not provider or not model:
        log.warning("entrada de cadeia inválida %r (esperado provedor:modelo)", target)
        return None
    return provider, model


def _parse_chains(raw: object) -> dict[str, list[tuple[str, str]]]:
    if not isinstance(raw, dict):
        if raw is not None:
            log.warning("chains da seção llm não é objeto; ignorado")
        return {}
    chains: dict[str, list[tuple[str, str]]] = {}
    for difficulty, entries in raw.items():
        key = str(difficulty).strip().lower()
        if key not in DIFFICULTIES:
            log.warning(
                "cadeia com difficulty desconhecida %r (esperado %s)",
                difficulty,
                "/".join(DIFFICULTIES),
            )
        if isinstance(entries, str):
            entries = [entries]
        if not isinstance(entries, list):
            log.warning("cadeia %r não é lista; ignorada", difficulty)
            continue
        parsed = [t for item in entries if (t := parse_target(str(item)))]
        chains[key] = parsed
    return chains


def parse_settings(section: dict) -> LLMSettings:
    """Interpreta a seção ``llm`` do ``aris_agent.json`` (dict vazio = padrões)."""
    section = dict(section or {})
    providers: dict[str, ProviderConfig] = {}
    raw_providers = section.get("providers")
    if isinstance(raw_providers, dict):
        for name, raw in raw_providers.items():
            if cfg := _parse_provider(str(name).strip().lower(), raw):
                providers[cfg.name] = cfg
    elif raw_providers is not None:
        log.warning("chave providers da seção llm não é objeto; ignorada")

    chains = _parse_chains(section.get("chains"))
    if not chains and providers:
        log.warning(
            "seção llm sem chains; o roteador usará a ordem dos provedores "
            "como cadeia implícita (exemplo em EXEMPLO_CADEIAS)"
        )

    return LLMSettings(
        providers=providers,
        chains=chains,
        max_wait_s=float(_num(section.get("max_wait_s", 10.0), 10.0, integer=False)),
        failure_threshold=max(1, int(_num(section.get("failure_threshold", 3), 3))),
        cooldown_s=float(_num(section.get("cooldown_s", 60.0), 60.0, integer=False)),
        stats_file=str(section.get("stats_file") or "llm_usage.json"),
    )
