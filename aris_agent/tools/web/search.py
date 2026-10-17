"""Busca na web com backends plugáveis (ordem vinda da configuração)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import requests

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ...contract.utils import redact_secrets
from ..registry import function_tool
from .output import wrap_result
from .settings import WebSettings, web_settings

log = logging.getLogger("aris.agent.tools.web.search")

MAX_RESULTS_CAP = 10

# Parâmetros de rastreio removidos na normalização (ajudam a deduplicar).
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = frozenset({"gclid", "fbclid", "msclkid", "ref", "ref_src", "igshid"})


class SearchError(Exception):
    """Todos os backends de busca falharam."""


@dataclass
class Hit:
    """Resultado de busca normalizado: título, URL e trecho."""

    title: str
    url: str
    snippet: str = ""


def unwrap_redirect(url: str) -> str:
    """Resolve redirecionadores embutidos na URL (google.com/url, duckduckgo.com/l)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host = (parts.hostname or "").lower()
    query = parse_qs(parts.query)
    target: str | None = None
    if host.endswith("google.com") and parts.path.startswith("/url"):
        target = (query.get("q") or query.get("url") or [None])[0]
    elif host.endswith("duckduckgo.com") and parts.path.startswith("/l/"):
        target = (query.get("uddg") or [None])[0]
    elif host.endswith("bing.com") and parts.path.startswith("/ck/a"):
        target = (query.get("u") or [None])[0]
    if target and target.startswith(("http://", "https://")):
        return target
    return url


def normalize_url(url: str) -> str:
    """Remove fragmento e parâmetros de rastreio para comparação/dedup."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    kept = [
        (k, v)
        for k, vs in parse_qs(parts.query, keep_blank_values=True).items()
        for v in vs
        if k.lower() not in _TRACKING_KEYS
        and not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit(
        ((parts.scheme or "https").lower(), (parts.netloc or "").lower(), path, urlencode(kept, doseq=True), "")
    )


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class Backend:
    """Interface de um backend de busca."""

    name = "base"
    env_key: str | None = None

    def available(self) -> bool:
        """True se o backend pode rodar agora (sem chave = sempre)."""
        return True

    def search(self, query: str, max_results: int, settings: WebSettings) -> list[Hit]:
        raise NotImplementedError


class DdgsBackend(Backend):
    """DuckDuckGo via biblioteca ``ddgs`` — não precisa de chave."""

    name = "ddgs"

    def search(self, query: str, max_results: int, settings: WebSettings) -> list[Hit]:
        from ddgs import DDGS

        with DDGS(timeout=max(3, int(settings.timeout_s))) as client:
            raw = client.text(query, max_results=max_results, safesearch="moderate")
        return [
            Hit(
                title=str(item.get("title") or "").strip(),
                url=str(item.get("href") or "").strip(),
                snippet=str(item.get("body") or "").strip(),
            )
            for item in raw
            if item.get("href")
        ]


class _RestBackend(Backend):
    """Backend REST com chave de API em variável de ambiente."""

    settings_timeout: float = 10.0

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def available(self) -> bool:
        return bool(self.env_key and os.environ.get(self.env_key))

    def _key(self) -> str:
        key = os.environ.get(self.env_key or "", "")
        if not key:
            raise SearchError(f"backend {self.name}: variável {self.env_key} ausente")
        return key

    def _get(self, url: str, **kwargs: Any) -> Any:
        try:
            resp = self._session.get(url, timeout=(5, self.settings_timeout), **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise SearchError(f"backend {self.name}: {exc}") from exc

    def _post(self, url: str, **kwargs: Any) -> Any:
        try:
            resp = self._session.post(url, timeout=(5, self.settings_timeout), **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise SearchError(f"backend {self.name}: {exc}") from exc


class BraveBackend(_RestBackend):
    """Brave Search API (``BRAVE_API_KEY``): GET /res/v1/web/search."""

    name = "brave"
    env_key = "BRAVE_API_KEY"
    _URL = "https://api.search.brave.com/res/v1/web/search"

    def search(self, query: str, max_results: int, settings: WebSettings) -> list[Hit]:
        self.settings_timeout = settings.timeout_s
        data = self._get(
            self._URL,
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": self._key(), "Accept": "application/json"},
        )
        out: list[Hit] = []
        for item in (data.get("web") or {}).get("results") or []:
            out.append(
                Hit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("description") or ""),
                )
            )
        return [h for h in out if h.url]


class TavilyBackend(_RestBackend):
    """Tavily (``TAVILY_API_KEY``): POST /search."""

    name = "tavily"
    env_key = "TAVILY_API_KEY"
    _URL = "https://api.tavily.com/search"

    def search(self, query: str, max_results: int, settings: WebSettings) -> list[Hit]:
        self.settings_timeout = settings.timeout_s
        data = self._post(
            self._URL,
            json={"query": query, "max_results": max_results, "search_depth": "basic"},
            headers={"Authorization": f"Bearer {self._key()}"},
        )
        out: list[Hit] = []
        for item in data.get("results") or []:
            out.append(
                Hit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("content") or ""),
                )
            )
        return [h for h in out if h.url]


class SerperBackend(_RestBackend):
    """Serper.dev (``SERPER_API_KEY``): POST google.serper.dev/search."""

    name = "serper"
    env_key = "SERPER_API_KEY"
    _URL = "https://google.serper.dev/search"

    def search(self, query: str, max_results: int, settings: WebSettings) -> list[Hit]:
        self.settings_timeout = settings.timeout_s
        data = self._post(
            self._URL,
            json={"q": query, "num": max_results},
            headers={"X-API-KEY": self._key(), "Content-Type": "application/json"},
        )
        out: list[Hit] = []
        for item in data.get("organic") or []:
            out.append(
                Hit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("link") or ""),
                    snippet=str(item.get("snippet") or ""),
                )
            )
        return [h for h in out if h.url]


_REGISTRY: dict[str, type[Backend]] = {
    "ddgs": DdgsBackend,
    "brave": BraveBackend,
    "tavily": TavilyBackend,
    "serper": SerperBackend,
}


def build_backends(settings: WebSettings) -> list[Backend]:
    """Instancia os backends pedidos na config, na ordem de preferência."""
    out: list[Backend] = []
    for name in settings.search_backends:
        cls = _REGISTRY.get(name)
        if cls is None:
            log.warning("backend de busca desconhecido na config: %r", name)
            continue
        out.append(cls())
    if not out:
        out = [DdgsBackend()]
    return out


def run_search(
    query: str, max_results: int, settings: WebSettings, backends: list[Backend] | None = None
) -> tuple[list[Hit], str]:
    """Tenta os backends em ordem até um devolver resultados.

    Devolve ``(hits, nome_do_backend)``. Levanta :class:`SearchError` se todos
    falharem. Resultados são normalizados (redirecionador resolvido), dedupados
    por URL e limitados a ``max_results`` (teto 10).
    """
    limit = max(1, min(int(max_results), MAX_RESULTS_CAP))
    chain = backends if backends is not None else build_backends(settings)
    failures: list[str] = []
    for backend in chain:
        if not backend.available():
            log.debug("backend %s indisponível (sem chave?); pulando", backend.name)
            continue
        try:
            hits = backend.search(query, limit, settings)
        except Exception as exc:  # noqa: BLE001 - falha de backend não pode derrubar a busca
            reason = redact_secrets(str(exc))
            log.warning("backend %s falhou: %s", backend.name, reason)
            failures.append(f"{backend.name}: {reason}")
            continue
        deduped = _dedupe(hits)
        if deduped:
            return deduped[:limit], backend.name
        failures.append(f"{backend.name}: sem resultados")
    raise SearchError("; ".join(failures) or "nenhum backend configurado")


def _dedupe(hits: list[Hit]) -> list[Hit]:
    seen: set[str] = set()
    out: list[Hit] = []
    for hit in hits:
        url = normalize_url(unwrap_redirect(hit.url))
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(Hit(title=hit.title.strip(), url=url, snippet=hit.snippet.strip()))
    return out


def format_hits(hits: list[Hit], backend: str) -> str:
    """Formata os resultados numerados para o LLM."""
    lines = [f"Backend: {backend}"]
    for i, hit in enumerate(hits, start=1):
        lines.append(f"[{i}] {hit.title or '(sem título)'}")
        lines.append(f"    {hit.url}")
        if hit.snippet:
            lines.append(f"    {hit.snippet}")
    return "\n".join(lines)


# ------------------------------------------------------------------- ferramenta

_SEARCH_SPEC = ToolSpec(
    name="web_search",
    description=(
        "Busca na web e devolve título, URL e trecho dos resultados. "
        "Backends em ordem de preferência da config (ddgs sem chave; brave/tavily/serper com chave)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Termo de busca"},
            "max_results": {
                "type": "integer",
                "description": "Quantidade de resultados (padrão 5, teto 10)",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    risk=Risk.READ,
    untrusted_output=True,
    timeout_s=30.0,
    tags=("web", "search"),
)


@function_tool(_SEARCH_SPEC)
def web_search(args: dict, ctx: ToolContext) -> ToolResult:
    """Busca na web com fallback entre backends; saída sempre envolta em wrap_untrusted."""
    query = str(args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, error="parâmetro 'query' é obrigatório")
    settings = web_settings(ctx.config)
    try:
        max_results = int(args.get("max_results") or settings.search_max_results)
    except (TypeError, ValueError):
        max_results = settings.search_max_results
    try:
        hits, backend = run_search(query, max_results, settings)
    except SearchError as exc:
        return ToolResult(ok=False, error=redact_secrets(f"busca falhou: {exc}"))
    if not hits:
        return ToolResult(
            ok=True,
            content=wrap_result(
                f"Backend: {backend}\nNenhum resultado para: {query}", "busca web", ctx.config, 1000
            ),
            data={"query": query, "backend": backend, "count": 0},
        )
    body = format_hits(hits, backend)
    return ToolResult(
        ok=True,
        content=wrap_result(body, "busca web", ctx.config, settings.max_chars),
        data={
            "query": query,
            "backend": backend,
            "count": len(hits),
            "urls": [hit.url for hit in hits],
        },
    )
