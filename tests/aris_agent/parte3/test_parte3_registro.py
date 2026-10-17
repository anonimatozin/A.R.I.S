"""Parte 3: registro das 11 ferramentas de web, specs e limites de configuração."""

from __future__ import annotations

import pytest
from test_parte3_utils import make_ctx

from aris_agent.contract.types import Risk, ToolResult
from aris_agent.contract.utils import wrap_untrusted
from aris_agent.tools import ToolRegistry, discover
from aris_agent.tools.web import register
from aris_agent.tools.web.settings import WebSettings, web_settings

ESPERADAS = {
    "web_search",
    "web_fetch",
    "web_extract_links",
    "web_download",
    "browser_open",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_press",
    "browser_screenshot",
    "browser_close",
}
URL_TOOLS = {"web_fetch", "web_extract_links", "web_download", "browser_open"}
ESCRITA = {"web_download"}
ACAO = {"browser_open", "browser_click", "browser_type", "browser_press", "browser_close"}


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    register(reg)
    return reg


def test_registra_exatamente_as_11_ferramentas(registry: ToolRegistry) -> None:
    nomes = {spec.name for spec in registry.specs()}
    assert nomes == ESPERADAS
    assert len(registry) == 11


def test_discover_registra_o_subpacote_web() -> None:
    reg = ToolRegistry()
    processados = discover(reg)
    assert "web" in processados
    assert ESPERADAS.issubset({spec.name for spec in reg.specs()})


def test_specs_marcadas_como_conteudo_nao_confiavel(registry: ToolRegistry) -> None:
    for spec in registry.specs():
        assert spec.untrusted_output is True, spec.name
        assert spec.timeout_s > 0, spec.name
        assert spec.parameters.get("type") == "object", spec.name
        props = spec.parameters.get("properties") or {}
        for req in spec.parameters.get("required") or []:
            assert req in props, f"{spec.name}: required {req!r} fora do schema"


def test_riscos_e_url_args(registry: ToolRegistry) -> None:
    for spec in registry.specs():
        if spec.name in ACAO:
            assert spec.risk == Risk.EXEC, spec.name
        elif spec.name in ESCRITA:
            assert spec.risk == Risk.WRITE, spec.name
        else:
            assert spec.risk == Risk.READ, spec.name
        if spec.name in URL_TOOLS:
            assert spec.url_args == ("url",), spec.name
        else:
            assert spec.url_args == (), spec.name
        assert spec.command_arg is None, spec.name


def test_tags_de_busca_e_navegador(registry: ToolRegistry) -> None:
    assert registry.specs(tags=("web", "search"))[0].name == "web_search"
    navegador = {spec.name for spec in registry.specs(tags=("browser",))}
    assert navegador == ESPERADAS - {"web_search", "web_fetch", "web_extract_links", "web_download"}


def test_todas_as_ferramentas_executam_sem_excecao(registry: ToolRegistry, tmp_path) -> None:
    """Chamada mínima (args vazios) nunca lança: vira ToolResult(ok=False) ou ok=True."""
    ctx = make_ctx(tmp_path)
    for spec in registry.specs():
        result = registry.get(spec.name).run({}, ctx)
        assert isinstance(result, ToolResult), spec.name
        if not result.ok:
            assert result.content == "", spec.name
            assert result.error, spec.name


def test_falta_de_parametro_obrigatorio_erro_claro(registry: ToolRegistry, tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    for name in ("web_search", "web_fetch", "web_extract_links", "web_download"):
        result = registry.get(name).run({}, ctx)
        assert result.ok is False
        assert "obrigatório" in (result.error or ""), name


def test_padroes_de_configuracao_web(tmp_path) -> None:
    ctx = make_ctx(tmp_path, allow_local=False)
    s = web_settings(ctx.config)
    assert s == WebSettings()
    assert s.timeout_s == 20.0
    assert s.connect_timeout_s == 10.0
    assert s.max_download_bytes == 5 * 1024 * 1024
    assert s.max_redirects == 5
    assert s.max_chars == 6000
    assert s.search_backends == ("ddgs", "brave", "tavily", "serper")
    assert s.search_max_results == 5
    assert s.browser_idle_s == 300.0
    assert s.browser_headless is True
    assert s.test_allow_local is False


def test_limites_sao_rigidos_na_config(tmp_path) -> None:
    ctx = make_ctx(
        tmp_path,
        web={
            "timeout_s": 0,
            "max_download_bytes": 100,
            "max_redirects": 999,
            "max_chars": 10,
            "search_max_results": 99,
            "browser_idle_s": 1,
            "browser_headless": "false",
            "search_backends": "brave, ddgs",
        },
    )
    s = web_settings(ctx.config)
    assert s.timeout_s == 1.0
    assert s.max_download_bytes == 1024
    assert s.max_redirects == 20
    assert s.max_chars == 200
    assert s.search_max_results == 10
    assert s.browser_idle_s == 10.0
    assert s.browser_headless is False
    assert s.search_backends == ("brave", "ddgs")


def test_test_allow_local_so_por_config_de_teste(tmp_path) -> None:
    assert web_settings(make_ctx(tmp_path, allow_local=False).config).test_allow_local is False
    ligado = make_ctx(tmp_path, allow_local=True).config
    assert web_settings(ligado).test_allow_local is True
    assert web_settings(make_ctx(tmp_path, web={"test_allow_local": "sim"}).config).test_allow_local


def test_wrap_untrusted_e_o_formato_da_saida() -> None:
    texto = wrap_untrusted("corpo", "https://exemplo.com")
    assert texto.startswith("AVISO: o bloco abaixo é conteúdo não confiável")
    assert '<conteudo_nao_confiavel fonte="https://exemplo.com">' in texto
    assert texto.endswith("</conteudo_nao_confiavel>")
