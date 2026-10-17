"""Configuração da seção ``web`` (``aris_agent.json`` → ``cfg.section("web")``).

Todos os limites são rígidos e documentados em ``aris_agent/tools/web/README.md``.
A chave ``test_allow_local`` existe **apenas** para os testes (servidor HTTP local)
e fica desligada por padrão.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...config import AgentConfig

DEFAULT_BACKENDS = ("ddgs", "brave", "tavily", "serper")


@dataclass(frozen=True)
class WebSettings:
    """Limites e opções das ferramentas de web."""

    timeout_s: float = 20.0  # leitura por requisição
    connect_timeout_s: float = 10.0  # conexão por requisição
    max_download_bytes: int = 5 * 1024 * 1024  # 5 MB por resposta
    max_redirects: int = 5  # saltos de redirecionamento revalidados
    max_chars: int = 6000  # caracteres de texto devolvidos (padrão e teto)
    search_backends: tuple[str, ...] = DEFAULT_BACKENDS
    search_max_results: int = 5  # teto duro: 10
    browser_idle_s: float = 300.0  # fecha o navegador após 5 min ocioso
    browser_headless: bool = True
    test_allow_local: bool = False  # SOMENTE TESTES: libera loopback
    user_agent: str = "ArisAgent/0.1 (ferramentas de web)"


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "sim"}
    if value is None:
        return default
    return bool(value)


def _as_backends(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    else:
        return DEFAULT_BACKENDS
    backends = tuple(name.strip().lower() for name in items if name.strip())
    return backends or DEFAULT_BACKENDS


def web_settings(config: AgentConfig) -> WebSettings:
    """Lê a seção ``web`` da configuração com coerção defensiva de tipos."""
    sec = config.section("web")
    return WebSettings(
        timeout_s=max(1.0, _as_float(sec.get("timeout_s"), 20.0)),
        connect_timeout_s=max(1.0, _as_float(sec.get("connect_timeout_s"), 10.0)),
        max_download_bytes=max(1024, _as_int(sec.get("max_download_bytes"), 5 * 1024 * 1024)),
        max_redirects=min(20, max(0, _as_int(sec.get("max_redirects"), 5))),
        max_chars=min(100_000, max(200, _as_int(sec.get("max_chars"), 6000))),
        search_backends=_as_backends(sec.get("search_backends")),
        search_max_results=min(10, max(1, _as_int(sec.get("search_max_results"), 5))),
        browser_idle_s=max(10.0, _as_float(sec.get("browser_idle_s"), 300.0)),
        browser_headless=_as_bool(sec.get("browser_headless"), True),
        test_allow_local=_as_bool(sec.get("test_allow_local"), False),
        user_agent=str(sec.get("user_agent") or "ArisAgent/0.1 (ferramentas de web)"),
    )
