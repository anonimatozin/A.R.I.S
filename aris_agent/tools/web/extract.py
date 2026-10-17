"""Extração de texto principal, título/data e links de páginas HTML."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

log = logging.getLogger("aris.agent.tools.web.extract")

try:  # trafilatura é pesado e opcional: sem ele, cai no fallback BeautifulSoup
    import trafilatura
except ImportError:  # pragma: no cover - depende do ambiente
    trafilatura = None  # type: ignore[assignment]

_MAX_LINK_TEXT = 120


@dataclass
class PageText:
    """Texto principal de uma página com metadados básicos."""

    text: str
    title: str = ""
    date: str = ""


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001 - lxml opcional
        return BeautifulSoup(html, "html.parser")


def _bs4_text(html: str) -> str:
    """Fallback simples: remove scripts/menus/rodapés e devolve o texto visível."""
    soup = _soup(html)
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer", "aside"]):
        tag.decompose()
    root = soup.body or soup
    lines = [line.strip() for line in root.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def extract_page(html: str, url: str) -> PageText:
    """Extrai o texto principal de ``html``; trafilatura com fallback bs4."""
    text = ""
    title = ""
    date = ""
    if trafilatura is not None:
        try:
            text = trafilatura.extract(
                html, url=url, include_comments=False, favor_recall=True
            ) or ""
            meta = trafilatura.extract_metadata(html, default_url=url)
            if meta is not None:
                title = (getattr(meta, "title", "") or "").strip()
                date = (getattr(meta, "date", "") or "").strip()
        except Exception as exc:  # noqa: BLE001 - página malformada não pode derrubar
            log.debug("trafilatura falhou em %s: %s", url, exc)
            text = ""
    if not text.strip():
        text = _bs4_text(html)
    if not title:
        soup = _soup(html)
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
    return PageText(text=text.strip(), title=title, date=date)


def looks_like_js_shell(html: str) -> bool:
    """Heurística: página vazia que só monta conteúdo com JavaScript."""
    probe = html[:200_000].lower()
    markers = ('id="root"', "id='root'", 'id="app"', "id='app'", "__next", "ng-app")
    has_app_marker = any(marker in probe for marker in markers)
    return has_app_marker and probe.count("<script") >= 2


def extract_links(html: str, base_url: str, max_links: int = 20) -> list[tuple[str, str]]:
    """Links relevantes de uma página: (texto, URL absoluta), sem duplicatas.

    Ignora ``#âncoras``, ``javascript:``, ``mailto:`` e esquemas não-http.
    Remove o fragmento (``#secao``) para deduplicar, e prefere links do mesmo
    domínio da página.
    """
    soup = _soup(html)
    seen: set[str] = set()
    same_domain: list[tuple[str, str]] = []
    others: list[tuple[str, str]] = []
    base_host = (urlsplit(base_url).hostname or "").lower()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        absolute = urldefrag(urljoin(base_url, href))[0]
        scheme = urlsplit(absolute).scheme.lower()
        if scheme not in ("http", "https"):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        text = " ".join(anchor.get_text(" ", strip=True).split())[:_MAX_LINK_TEXT]
        if not text:
            text = absolute
        item = (text, absolute)
        if (urlsplit(absolute).hostname or "").lower() == base_host:
            same_domain.append(item)
        else:
            others.append(item)
    return (same_domain + others)[:max_links]
