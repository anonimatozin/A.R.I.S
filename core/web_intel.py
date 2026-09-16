"""Web Intelligence — busca web e pesquisa profunda.

Modulo autonomo que nao depende de APIs externas.
Usa DuckDuckGo HTML para busca e urllib para fetch.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any


# ── HTML Parser para DuckDuckGo ──────────────────────────────

class _DDGParser(HTMLParser):
    """Extrai resultados de busca do DuckDuckGo HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._in_title = False
        self._in_snippet = False
        self._current: dict[str, str] = {}
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        cls = attr_dict.get("class", "")

        if tag == "a" and "result__a" in cls:
            self._in_title = True
            self._current["url"] = attr_dict.get("href", "")
            self._current["title"] = ""

        if tag == "a" and "result__snippet" in cls:
            self._in_snippet = True
            self._current["snippet"] = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        if tag == "a" and self._in_snippet:
            self._in_snippet = False
            if self._current.get("title"):
                self.results.append(self._current.copy())
            self._current = {}

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._current["title"] = self._current.get("title", "") + data
        if self._in_snippet:
            self._current["snippet"] = self._current.get("snippet", "") + data


class _HTMLTextExtractor(HTMLParser):
    """Extrai texto limpo de uma pagina HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._text: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "noscript", "svg", "iframe"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._text.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._text)


# ── Web Search ────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

_SEARCH_TIMEOUT = 8
_FETCH_TIMEOUT = 8


def web_search(query: str, max_results: int = 8) -> dict[str, Any]:
    """Busca web via DuckDuckGo HTML. Sem API key."""
    if not query:
        return {"ok": False, "error": "Query vazia"}

    import concurrent.futures

    def _do_search():
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_SEARCH_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        parser = _DDGParser()
        parser.feed(html)
        return parser.results[:max_results]

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_search)
            results = future.result(timeout=_SEARCH_TIMEOUT + 2)
        return {
            "ok": True,
            "query": query,
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "query": query}


# ── Web Fetch ─────────────────────────────────────────────────

def web_fetch(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """Busca e extrai texto de uma URL."""
    if not url:
        return {"ok": False, "error": "URL vazia"}

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/" not in content_type:
                return {"ok": False, "error": f"Tipo nao suportado: {content_type}"}
            html = resp.read().decode("utf-8", errors="replace")

        extractor = _HTMLTextExtractor()
        extractor.feed(html)
        text = extractor.get_text()

        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        return {
            "ok": True,
            "url": url,
            "text": text,
            "length": len(text),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}


# ── Deep Research ─────────────────────────────────────────────

@dataclass
class ResearchResult:
    """Resultado de uma pesquisa profunda."""
    query: str
    summary: str = ""
    sources: list[dict[str, str]] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    depth: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "summary": self.summary,
            "sources": self.sources,
            "facts": self.facts,
            "depth": self.depth,
        }


def deep_research(query: str, depth: int = 2) -> dict[str, Any]:
    """Pesquisa profunda multi-step.

    1. Busca inicial
    2. Le os top 3 resultados
    3. Gera query de Follow-up baseada no que encontrou
    4. Busca novamente
    5. Agrega tudo
    """
    if not query:
        return {"ok": False, "error": "Query vazia"}

    depth = min(max(depth, 1), 4)
    result = ResearchResult(query=query, depth=depth)
    all_facts: list[str] = []
    all_sources: list[dict[str, str]] = []

    try:
        # Step 1: Busca inicial
        search1 = web_search(query, max_results=5)
        if not search1.get("ok"):
            return {"ok": False, "error": search1.get("error", "Busca falhou")}

        for r in search1.get("results", []):
            if r.get("url"):
                all_sources.append({"title": r.get("title", ""), "url": r["url"]})

        # Step 2: Le os top resultados
        fetched_texts: list[str] = []
        for r in search1.get("results", [])[:3]:
            url = r.get("url", "")
            if not url or not url.startswith("http"):
                continue
            fetched = web_fetch(url, max_chars=4000)
            if fetched.get("ok") and fetched.get("text"):
                text = fetched["text"]
                fetched_texts.append(text)
                # Extrai fatos sentenciais
                sentences = re.split(r'(?<=[.!?])\s+', text)
                for s in sentences:
                    s = s.strip()
                    if len(s) > 40 and len(s) < 300:
                        if not any(skip in s.lower() for skip in ["cookie", "privacy", "terms", "subscribe", "click here"]):
                            all_facts.append(s)

        # Step 3: Gera follow-up query (se depth > 1)
        if depth > 1 and all_facts:
            key_phrase = all_facts[0][:100]
            follow_query = f"{query} {key_phrase.split()[:5] if key_phrase else 'detalhes'}"
            search2 = web_search(follow_query, max_results=3)
            if search2.get("ok"):
                for r in search2.get("results", []):
                    if r.get("url"):
                        all_sources.append({"title": r.get("title", ""), "url": r["url"]})

                for r in search2.get("results", [])[:2]:
                    url = r.get("url", "")
                    if not url or not url.startswith("http"):
                        continue
                    fetched = web_fetch(url, max_chars=3000)
                    if fetched.get("ok") and fetched.get("text"):
                        sentences = re.split(r'(?<=[.!?])\s+', fetched["text"])
                        for s in sentences:
                            s = s.strip()
                            if 40 < len(s) < 300:
                                if not any(skip in s.lower() for skip in ["cookie", "privacy", "terms"]):
                                    all_facts.append(s)

        # Agrega
        unique_facts = list(dict.fromkeys(all_facts))[:15]
        unique_sources = list({s["url"]: s for s in all_sources}.values())[:8]

        result.sources = unique_sources
        result.facts = unique_facts
        result.summary = f"Encontrados {len(unique_facts)} fatos de {len(unique_sources)} fontes."

        return {
            "ok": True,
            "query": query,
            "summary": result.summary,
            "sources": result.sources,
            "facts": result.facts,
            "depth": depth,
        }

    except Exception as e:
        return {"ok": False, "error": str(e), "query": query}


# ── Quick Answer ──────────────────────────────────────────────

def quick_answer(question: str) -> dict[str, Any]:
    """Busca rapida e retorna resposta concisa."""
    search = web_search(question, max_results=3)
    if not search.get("ok"):
        return {"ok": False, "error": search.get("error")}

    snippets = []
    for r in search.get("results", []):
        if r.get("snippet"):
            snippets.append(r["snippet"])

    combined = " | ".join(snippets[:3]) if snippets else "Nao encontrei nada."

    return {
        "ok": True,
        "question": question,
        "answer": combined,
        "sources": [r.get("url", "") for r in search.get("results", [])[:3]],
    }
