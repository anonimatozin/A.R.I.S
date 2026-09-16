"""Intelligence Tools — ferramentas internas de pesquisa do A.R.I.S.

Tools internas do AgentLoop:
- search: busca web simples (1 query)
- research: pesquisa aprofundada (multi-step)
- verify: verificacao de fatos (compara fontes)
- compare: comparacao lado a lado
- latest: noticias mais recentes

Todas usam websearch/webfetch por baixo.
Nao sao expostas diretamente ao usuario — sao chamadas pelo AgentLoop.
"""

from __future__ import annotations

from typing import Any

# ── Definicoes das tools ──────────────────────────────────────

INTELLIGENCE_TOOLS: dict[str, dict[str, Any]] = {
    "intel_search": {
        "description": "Busca web simples. Retorna resumo de resultados relevantes.",
        "permission": "safe",
        "category": "intelligence",
        "params": ["query"],
    },
    "intel_research": {
        "description": "Pesquisa aprofundada multi-step. Busca, resume, busca mais, agrega.",
        "permission": "safe",
        "category": "intelligence",
        "params": ["query", "depth"],
    },
    "intel_verify": {
        "description": "Verificacao de fatos. Busca multiplas fontes e compara informacoes.",
        "permission": "safe",
        "category": "intelligence",
        "params": ["claim"],
    },
    "intel_compare": {
        "description": "Comparacao lado a lado de dois items/opcoes/tecnologias.",
        "permission": "safe",
        "category": "intelligence",
        "params": ["item_a", "item_b", "aspect"],
    },
    "intel_latest": {
        "description": "Retorna a noticia/informacao mais recente sobre um assunto.",
        "permission": "safe",
        "category": "intelligence",
        "params": ["topic"],
    },
}


class IntelSearch:
    """Busca web simples."""

    def __init__(self, websearch_fn: Any = None) -> None:
        self._search = websearch_fn

    def execute(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Executa busca e retorna resumo."""
        if not query:
            return {"ok": False, "error": "Query vazia"}

        try:
            results = self._do_search(query)
            return {
                "ok": True,
                "query": query,
                "results": results,
                "count": len(results),
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "query": query}

    def _do_search(self, query: str) -> list[dict[str, str]]:
        """Busca real (stub — integra com websearch module)."""
        # Stub que retorna estrutura consistente
        # Em producao, chama websearch.websearch()
        return [{"title": query, "snippet": f"Resultado para: {query}", "url": ""}]


class IntelResearch:
    """Pesquisa aprofundada multi-step.

    Fluxo:
    1. Busca inicial
    2. Resume resultados
    3. Identifica gaps
    4. Busca complementos
    5. Agrega tudo
    """

    MAX_STEPS = 3

    def __init__(self, search: IntelSearch | None = None) -> None:
        self._search = search or IntelSearch()

    def execute(self, query: str, depth: int = 2, **kwargs: Any) -> dict[str, Any]:
        """Executa pesquisa aprofundada."""
        if not query:
            return {"ok": False, "error": "Query vazia"}

        depth = min(depth, self.MAX_STEPS)
        all_findings: list[dict[str, Any]] = []
        queries_used: list[str] = [query]

        # Step 1: Busca inicial
        initial = self._search.execute(query)
        if initial.get("ok"):
            all_findings.append({
                "step": 1,
                "query": query,
                "results": initial.get("results", []),
            })

        # Steps 2+: Buscas complementares
        for step in range(2, depth + 1):
            sub_query = self._derive_subquery(query, all_findings, step)
            if sub_query and sub_query not in queries_used:
                queries_used.append(sub_query)
                result = self._search.execute(sub_query)
                if result.get("ok"):
                    all_findings.append({
                        "step": step,
                        "query": sub_query,
                        "results": result.get("results", []),
                    })

        # Agregar
        summary = self._aggregate(query, all_findings)

        return {
            "ok": True,
            "query": query,
            "depth": depth,
            "steps": len(all_findings),
            "queries_used": queries_used,
            "findings": all_findings,
            "summary": summary,
        }

    def _derive_subquery(self, original: str, findings: list, step: int) -> str:
        """Deriva sub-query baseado nos findings anteriores."""
        if step == 2:
            return f"{original} detalhes"
        if step == 3:
            return f"{original} exemplos praticos"
        return f"{original} complementar"

    def _aggregate(self, query: str, findings: list) -> str:
        """Agrega findings em resumo."""
        total = sum(len(f.get("results", [])) for f in findings)
        steps = len(findings)
        return f"Pesquisa sobre '{query}': {steps} etapas, {total} resultados encontrados."


class IntelVerify:
    """Verificacao de fatos.

    Busca multiplas fontes e compara informacoes.
    Retorna confianca baseada em concordancia.
    """

    def __init__(self, search: IntelSearch | None = None) -> None:
        self._search = search or IntelSearch()

    def execute(self, claim: str, **kwargs: Any) -> dict[str, Any]:
        """Verifica uma alegacao."""
        if not claim:
            return {"ok": False, "error": "Alegacao vazia"}

        # Buscar variantes da claim
        queries = [
            claim,
            f"{' '.join(claim.split()[:5])} verdade ou mentira",
            f"{' '.join(claim.split()[:5])} fatos",
        ]

        sources: list[dict[str, Any]] = []
        for q in queries:
            result = self._search.execute(q)
            if result.get("ok"):
                sources.extend(result.get("results", []))

        # Analise basica de concordancia
        confidence = self._analyze_agreement(claim, sources)

        return {
            "ok": True,
            "claim": claim,
            "sources_checked": len(sources),
            "confidence": confidence,
            "sources": sources[:10],  # top 10
            "verdict": self._get_verdict(confidence),
        }

    def _analyze_agreement(self, claim: str, sources: list) -> float:
        """Analisa concordancia entre fontes (stub)."""
        if not sources:
            return 0.0
        # Stub: retorna confidence baseado no numero de fontes
        return min(len(sources) / 5.0, 1.0)

    def _get_verdict(self, confidence: float) -> str:
        """Retorna veredicto baseado na confidence."""
        if confidence >= 0.8:
            return "Alta confianca — provavelmente verdadeiro"
        if confidence >= 0.5:
            return "Confianca media — requer verificacao adicional"
        return "Baixa confianca — informacao inconclusiva"


class IntelCompare:
    """Comparacao lado a lado."""

    def __init__(self, search: IntelSearch | None = None) -> None:
        self._search = search or IntelSearch()

    def execute(self, item_a: str, item_b: str, aspect: str = "",
                **kwargs: Any) -> dict[str, Any]:
        """Compara dois items."""
        if not item_a or not item_b:
            return {"ok": False, "error": "Dois items sao necessarios"}

        aspect_suffix = f" {aspect}" if aspect else ""

        # Buscar info de cada item
        info_a = self._search.execute(f"{item_a}{aspect_suffix}")
        info_b = self._search.execute(f"{item_b}{aspect_suffix}")

        # Buscar comparacao direta
        direct = self._search.execute(f"{item_a} vs {item_b}{aspect_suffix}")

        return {
            "ok": True,
            "item_a": item_a,
            "item_b": item_b,
            "aspect": aspect,
            "info_a": info_a.get("results", []),
            "info_b": info_b.get("results", []),
            "direct_comparison": direct.get("results", []),
        }


class IntelLatest:
    """Noticias mais recentes."""

    def __init__(self, search: IntelSearch | None = None) -> None:
        self._search = search or IntelSearch()

    def execute(self, topic: str, **kwargs: Any) -> dict[str, Any]:
        """Busca noticia mais recente."""
        if not topic:
            return {"ok": False, "error": "Topico vazio"}

        queries = [
            f"{topic} ultima noticia hoje",
            f"{topic} noticia recente 2026",
        ]

        all_results: list[dict[str, str]] = []
        for q in queries:
            result = self._search.execute(q)
            if result.get("ok"):
                all_results.extend(result.get("results", []))

        return {
            "ok": True,
            "topic": topic,
            "results": all_results,
            "count": len(all_results),
        }


# ── Executors ─────────────────────────────────────────────────

_search_instance: IntelSearch | None = None


def _get_search() -> IntelSearch:
    global _search_instance
    if _search_instance is None:
        _search_instance = IntelSearch()
    return _search_instance


def execute_intel_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Executa uma intelligence tool."""
    search = _get_search()

    if tool_name == "intel_search":
        return IntelSearch(search).execute(
            query=params.get("query", ""),
        )
    if tool_name == "intel_research":
        return IntelResearch(search).execute(
            query=params.get("query", ""),
            depth=params.get("depth", 2),
        )
    if tool_name == "intel_verify":
        return IntelVerify(search).execute(
            claim=params.get("claim", ""),
        )
    if tool_name == "intel_compare":
        return IntelCompare(search).execute(
            item_a=params.get("item_a", ""),
            item_b=params.get("item_b", ""),
            aspect=params.get("aspect", ""),
        )
    if tool_name == "intel_latest":
        return IntelLatest(search).execute(
            topic=params.get("topic", ""),
        )
    return {"ok": False, "error": f"Unknown intel tool: {tool_name}"}
