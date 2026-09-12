"""Hyper Search Engine do A.R.I.S.

Sistema de pesquisa inteligente multi-fonte.
Consulta multiplas fontes, compara e consolida resultados.
"""

import json
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote_plus
from dataclasses import dataclass

from core.rate_limiter import serpapi_limiter


@dataclass
class SearchResult:
    """Resultado de uma fonte de pesquisa."""
    source: str
    title: str
    snippet: str
    url: str


class HyperSearch:
    """Motor de pesquisa multi-fonte.

    Consulta múltiplas fontes e consolida os resultados.
    """

    def __init__(self, api_keys: dict[str, str] | None = None) -> None:
        """Inicializa o motor.

        Args:
            api_keys: Chaves de API para cada serviço.
        """
        self._api_keys = api_keys or {}
        self._sources: list[str] = []

        if self._api_keys.get("serpapi"):
            self._sources.append("serpapi")

    @property
    def available_sources(self) -> list[str]:
        """Fontes disponíveis."""
        return self._sources.copy()

    def _search_serpapi(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Pesquisa via SerpAPI (Google)."""
        key = self._api_keys.get("serpapi")
        if not key:
            return []

        if not serpapi_limiter.allow():
            return [SearchResult(
                source="SerpAPI",
                title="Rate limit atingido",
                snippet=f"Tente novamente em alguns segundos. Quota: {serpapi_limiter.remaining}/{serpapi_limiter.max_calls}",
                url="",
            )]

        try:
            url = (
                f"https://serpapi.com/search.json"
                f"?q={quote_plus(query)}&api_key={key}&num={limit}&hl=pt-br"
            )
            req = Request(url, headers={"User-Agent": "ARIS-NEXUS/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            results = []
            for item in data.get("organic_results", [])[:limit]:
                results.append(SearchResult(
                    source="Google",
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    url=item.get("link", ""),
                ))
            return results
        except Exception:
            return []

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Executa pesquisa em todas as fontes.

        Args:
            query: Termo de pesquisa.
            limit: Limite de resultados por fonte.

        Returns:
            Lista consolidada de resultados.
        """
        all_results = []

        if "serpapi" in self._sources:
            all_results.extend(self._search_serpapi(query, limit))

        return all_results

    def search_and_summarize(self, query: str) -> str:
        """Pesquisa e gera resumo consolidado.

        Args:
            query: Termo de pesquisa.

        Returns:
            Resumo formatado dos resultados.
        """
        results = self.search(query)

        if not results:
            return (
                f"getResultados para '{query}': Nenhum resultado encontrado.\n"
                f"Fontes disponíveis: {len(self._sources)}\n"
                f"Dica: Configure SERPAPI_KEY no .env para pesquisa via Google."
            )

        lines = [
            f"Resultados para '{query}'",
            f"Fontes consultadas: {len(self._sources)}",
            "",
        ]

        for i, r in enumerate(results[:5], 1):
            lines.append(f"{i}. {r.title}")
            if r.snippet:
                lines.append(f"   {r.snippet[:120]}...")
            lines.append("")

        lines.append(f"Total: {len(results)} resultados de {len(self._sources)} fonte(s)")

        return "\n".join(lines)
