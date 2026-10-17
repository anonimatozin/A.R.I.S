"""Parte 3: extração de texto principal, shell de JS e links (sem rede)."""

from __future__ import annotations

from test_parte3_utils import HTML_ARTIGO

from aris_agent.tools.web import extract as extract_mod
from aris_agent.tools.web.extract import (
    PageText,
    extract_links,
    extract_page,
    looks_like_js_shell,
)

BASE = "https://exemplo.com/artigo/index.html"


def test_extract_page_com_trafilatura() -> None:
    page = extract_page(HTML_ARTIGO, BASE)
    assert isinstance(page, PageText)
    assert "parágrafo principal do artigo" in page.text
    # trafilatura prefere o <h1>; o <title> é o fallback (testado abaixo)
    assert page.title in ("Título do Artigo", "Artigo de Teste")
    assert page.title.strip() != ""


def test_extract_page_fallback_sem_trafilatura(monkeypatch) -> None:
    monkeypatch.setattr(extract_mod, "trafilatura", None)
    page = extract_page(HTML_ARTIGO, BASE)
    assert "parágrafo principal do artigo" in page.text
    assert "Rodapé do site" not in page.text, "fallback deve descartar rodapé"
    assert "Início Sobre" not in page.text, "fallback deve descartar menu"
    assert page.title == "Artigo de Teste"


def test_extract_page_vazio() -> None:
    page = extract_page("", BASE)
    assert page.text == ""
    assert page.title == ""


def test_extract_page_html_quebrado_nao_levanta(monkeypatch) -> None:
    monkeypatch.setattr(extract_mod, "trafilatura", None)
    page = extract_page("<html><body><p>oi<div></span>", BASE)
    assert "oi" in page.text


def test_looks_like_js_shell() -> None:
    shell = '<div id="root"></div><script src="a.js"></script><script src="b.js"></script>'
    assert looks_like_js_shell(shell) is True
    assert looks_like_js_shell("<p>uma frase com id= raiz</p>") is False
    assert looks_like_js_shell('<div id="app"></div><script src="a.js"></script>') is False
    assert looks_like_js_shell(HTML_ARTIGO) is False


def test_extract_links_resolve_e_filtra() -> None:
    html = """
    <a href="/a">A</a>
    <a href="b.html">B</a>
    <a href="https://exemplo.com/c">C</a>
    <a href="https://outra.example.net/d">D</a>
    <a href="#topo">ancora</a>
    <a href="javascript:alert(1)">js</a>
    <a href="mailto:x@y.z">mail</a>
    <a href="ftp://files.example.com/z">ftp</a>
    <a href="https://exemplo.com/a">A2</a>
    <a href="/sem-texto"></a>
    """
    links = extract_links(html, BASE, max_links=50)
    urls = [url for _t, url in links]
    assert urls[0] == "https://exemplo.com/a"
    assert "https://exemplo.com/artigo/b.html" in urls, "relativa resolve contra a página"
    assert "https://outra.example.net/d" in urls
    assert urls.count("https://exemplo.com/a") == 1, "dedupe por URL"
    for ruim in ("#topo", "javascript:", "mailto:", "ftp:"):
        assert not any(ruim in u for u in urls), ruim
    assert urls.index("https://exemplo.com/a") < urls.index("https://outra.example.net/d")
    assert links[-1][1] == "https://outra.example.net/d", "externos vão por último"
    assert dict(links)["https://exemplo.com/sem-texto"] == "https://exemplo.com/sem-texto", (
        "sem texto usa a URL"
    )


def test_extract_links_respeita_max_links() -> None:
    html = "".join(f'<a href="/p{i}">P{i}</a>' for i in range(10))
    assert len(extract_links(html, BASE, max_links=3)) == 3


def test_extract_links_sem_ancoras_nem_duplicatas() -> None:
    html = '<a href="/x">1</a><a href="/x#s">2</a><a href="/x">3</a>'
    urls = [url for _t, url in extract_links(html, BASE)]
    assert urls == ["https://exemplo.com/x"], "âncora interna vira a mesma URL"


def test_extract_page_titulo_fallback() -> None:
    html = "<html><head><title>  Título Com Espaços  </title></head><body><p>x</p></body></html>"
    page = extract_page(html, BASE)
    assert page.title == "Título Com Espaços"
