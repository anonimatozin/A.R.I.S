"""Parte 3: backends de busca, normalização/dedup e a ferramenta web_search."""

from __future__ import annotations

import pytest
from test_parte3_utils import make_ctx

from aris_agent.tools.web import search as search_mod
from aris_agent.tools.web.search import (
    Backend,
    BraveBackend,
    DdgsBackend,
    Hit,
    SerperBackend,
    TavilyBackend,
    WebSettings,
    build_backends,
    format_hits,
    normalize_url,
    run_search,
    unwrap_redirect,
    web_search,
)


class FakeBackend(Backend):
    """Backend de teste: devolve hits prontos ou falha à vontade."""

    def __init__(self, name: str, hits: list[Hit] | None = None, erro: str | None = None,
                 disponivel: bool = True) -> None:
        self.name = name
        self._hits = hits or []
        self._erro = erro
        self._disponivel = disponivel

    def available(self) -> bool:
        return self._disponivel

    def search(self, query: str, max_results: int, settings: WebSettings) -> list[Hit]:
        if self._erro:
            raise RuntimeError(self._erro)
        return self._hits


def _hits(n: int) -> list[Hit]:
    return [Hit(title=f"T{i}", url=f"https://exemplo.com/p{i}", snippet=f"S{i}") for i in range(n)]


# --------------------------------------------------------------- normalização


def test_unwrap_redirect_google() -> None:
    url = "https://www.google.com/url?q=https%3A%2F%2Fexemplo.com%2Fdestino&sa=U"
    assert unwrap_redirect(url) == "https://exemplo.com/destino"


def test_unwrap_redirect_duckduckgo() -> None:
    url = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexemplo.com%2Fx&t=ab"
    assert unwrap_redirect(url) == "https://exemplo.com/x"


def test_unwrap_redirect_bing_e_urls_normais() -> None:
    assert (
        unwrap_redirect("https://www.bing.com/ck/a?u=https%3A%2F%2Fexemplo.com%2Fy&f=1")
        == "https://exemplo.com/y"
    )
    normal = "https://exemplo.com/direto?x=1"
    assert unwrap_redirect(normal) == normal


def test_normalize_remove_rastreio_e_fragmento() -> None:
    assert (
        normalize_url("https://Exemplo.com/p/?utm_source=x&utm_medium=y&gclid=1&q=2#sec")
        == "https://exemplo.com/p?q=2"
    )
    assert normalize_url("https://exemplo.com/") == "https://exemplo.com/"
    assert normalize_url("https://exemplo.com") == "https://exemplo.com/"


# ------------------------------------------------------------------- backends


def test_build_backends_na_ordem_da_config() -> None:
    settings = WebSettings(search_backends=("serper", "ddgs"))
    assert [b.name for b in build_backends(settings)] == ["serper", "ddgs"]


def test_build_backends_desconhecido_vai_para_ddgs() -> None:
    settings = WebSettings(search_backends=("nao-existe",))
    assert [type(b).__name__ for b in build_backends(settings)] == ["DdgsBackend"]


def test_disponibilidade_exige_chave(monkeypatch) -> None:
    for env in ("BRAVE_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    assert DdgsBackend().available() is True
    assert BraveBackend().available() is False
    assert TavilyBackend().available() is False
    assert SerperBackend().available() is False
    monkeypatch.setenv("BRAVE_API_KEY", "chave-simulada")
    assert BraveBackend().available() is True


# ------------------------------------------------------------------ run_search


def test_run_search_usa_primeiro_backend_ok() -> None:
    backends = [FakeBackend("um", _hits(3)), FakeBackend("dois", _hits(3))]
    hits, nome = run_search("algo", 5, WebSettings(), backends)
    assert nome == "um"
    assert len(hits) == 3


def test_run_search_fallback_quando_primeiro_falha() -> None:
    backends = [FakeBackend("um", erro="boom"), FakeBackend("dois", _hits(2))]
    hits, nome = run_search("algo", 5, WebSettings(), backends)
    assert nome == "dois"
    assert len(hits) == 2


def test_run_search_pula_backend_indisponivel() -> None:
    backends = [FakeBackend("off", _hits(9), disponivel=False), FakeBackend("on", _hits(1))]
    hits, nome = run_search("algo", 5, WebSettings(), backends)
    assert nome == "on"
    assert len(hits) == 1


def test_run_search_deduplica_e_normaliza() -> None:
    bruto = [
        Hit("A", "https://exemplo.com/p?utm_source=x", "s"),
        Hit("A2", "https://exemplo.com/p", "s"),
        Hit(
            "B",
            "https://www.google.com/url?q=https%3A%2F%2Fexemplo.com%2Fq&sa=U",
            "s",
        ),
    ]
    hits, _ = run_search("algo", 5, WebSettings(), [FakeBackend("fake", bruto)])
    assert [h.url for h in hits] == ["https://exemplo.com/p", "https://exemplo.com/q"]


def test_run_search_limita_a_10() -> None:
    hits, _ = run_search("algo", 999, WebSettings(), [FakeBackend("fake", _hits(15))])
    assert len(hits) == 10
    hits2, _ = run_search("algo", 3, WebSettings(), [FakeBackend("fake", _hits(15))])
    assert len(hits2) == 3


def test_run_search_sem_resultados_reclama() -> None:
    backends = [FakeBackend("um", []), FakeBackend("dois", [])]
    with pytest.raises(Exception) as exc:
        run_search("algo", 5, WebSettings(), backends)
    assert "sem resultados" in str(exc.value) or "nenhum backend" in str(exc.value)


def test_run_search_sem_backend_configurado() -> None:
    with pytest.raises(Exception) as exc:
        run_search("algo", 5, WebSettings(), [FakeBackend("off", disponivel=False)])
    assert "nenhum backend configurado" in str(exc.value)


def test_format_hits() -> None:
    texto = format_hits(_hits(2), "ddgs")
    assert texto.startswith("Backend: ddgs")
    assert "[1] T0" in texto
    assert "https://exemplo.com/p1" in texto


# ------------------------------------------------------------------ ferramenta


def test_web_search_devolve_resultados_envoltos(tmp_path, monkeypatch) -> None:
    chamado: dict = {}

    def fake(query, max_results, settings):
        chamado.update(query=query, max_results=max_results)
        return _hits(2), "fake"

    monkeypatch.setattr(search_mod, "run_search", fake)
    result = web_search.run({"query": "python"}, make_ctx(tmp_path))
    assert result.ok, result.error
    assert chamado == {"query": "python", "max_results": 5}
    assert result.content.startswith("AVISO:")
    assert '<conteudo_nao_confiavel fonte="busca web">' in result.content
    assert "[1] T0" in result.content
    assert "https://exemplo.com/p1" in result.content
    assert result.data["count"] == 2
    assert result.data["backend"] == "fake"


def test_web_search_max_results_do_argumento(tmp_path, monkeypatch) -> None:
    chamado: dict = {}

    def fake(query, max_results, settings):
        chamado["max_results"] = max_results
        return _hits(max_results), "fake"

    monkeypatch.setattr(search_mod, "run_search", fake)
    result = web_search.run({"query": "x", "max_results": 7}, make_ctx(tmp_path))
    assert result.ok and chamado["max_results"] == 7
    assert result.data["count"] == 7


def test_web_search_query_vazia(tmp_path) -> None:
    result = web_search.run({"query": "   "}, make_ctx(tmp_path))
    assert result.ok is False
    assert "obrigatório" in (result.error or "")


def test_web_search_falha_vira_erro(tmp_path, monkeypatch) -> None:
    def fake(query, max_results, settings):
        from aris_agent.tools.web.search import SearchError

        raise SearchError("sem rede")

    monkeypatch.setattr(search_mod, "run_search", fake)
    result = web_search.run({"query": "x"}, make_ctx(tmp_path))
    assert result.ok is False
    assert "busca falhou" in (result.error or "")
    assert "sem rede" in (result.error or "")
    assert result.content == ""


def test_web_search_sem_resultados(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(search_mod, "run_search", lambda *a, **k: ([], "fake"))
    result = web_search.run({"query": "zzz"}, make_ctx(tmp_path))
    assert result.ok is True
    assert "Nenhum resultado" in result.content
    assert result.data["count"] == 0


# ---------------------------------------------------------------------- live


@pytest.mark.live
def test_live_busca_real_ddgs() -> None:
    hits, backend = run_search("Python programming language", 3, WebSettings())
    assert hits, "busca real não devolveu resultados"
    assert backend in {"ddgs", "brave", "tavily", "serper"}
    assert all(h.url.startswith(("http://", "https://")) for h in hits)
