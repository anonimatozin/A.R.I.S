"""Parte 3: web_fetch e web_extract_links contra um servidor HTTP local."""

from __future__ import annotations

from test_parte3_utils import HTML_ARTIGO, local_server, make_ctx

from aris_agent.tools.web.pages import web_extract_links, web_fetch

LONG_HTML = (
    "<!doctype html><html><head><title>Página Longa</title></head><body><article>"
    + "".join(
        "<p>"
        + " ".join(f"Sentença {i}.{j} do parágrafo longo de teste." for j in range(15))
        + "</p>"
        for i in range(40)
    )
    + "</article></body></html>"
)
SHELL_HTML = """<!doctype html><html><head><title>SPA</title></head>
<body><div id="root"></div>
<script src="/a.js"></script><script src="/b.js"></script><script src="/c.js"></script>
</body></html>"""
LINKS_HTML = """<!doctype html><html><head><title>Links</title></head><body>
<a href="/interno">Página interna</a>
<a href="relativa">Relativa</a>
<a href="/interno">Página interna</a>
<a href="https://exemplo.org/fora">Externo</a>
<a href="#topo">Âncora</a>
<a href="javascript:void(0)">JS</a>
<a href="mailto:vinicius@example.com">E-mail</a>
<a href="ftp://files.example.com/a.zip">FTP</a>
<a href="tel:+5511999999999">Telefone</a>
</body></html>"""


def _html(content: str) -> tuple[int, dict, bytes]:
    return 200, {"Content-Type": "text/html; charset=utf-8"}, content.encode("utf-8")


def test_fetch_devolve_texto_principal_com_aviso(tmp_path) -> None:
    with local_server({"/": _html(HTML_ARTIGO)}) as base:
        result = web_fetch.run({"url": base + "/"}, make_ctx(tmp_path))
    assert result.ok, result.error
    assert result.content.startswith("AVISO: o bloco abaixo é conteúdo não confiável")
    assert "<conteudo_nao_confiavel" in result.content
    assert "parágrafo principal do artigo" in result.content
    assert "URL final: " + base + "/" in result.content
    assert "Título: " in result.content
    assert result.data["url"] == base + "/"
    assert result.data["chars"] > 0
    assert len(result.content) <= 8000


def test_fetch_segue_redirect_relativo(tmp_path) -> None:
    rotas = {
        "/old": (302, {"Location": "/new"}, b""),
        "/new": _html(HTML_ARTIGO),
    }
    with local_server(rotas) as base:
        result = web_fetch.run({"url": base + "/old"}, make_ctx(tmp_path))
    assert result.ok, result.error
    assert result.data["url"] == base + "/new"
    assert base + "/old" in result.data["redirects"]


def test_fetch_bloqueia_redirect_para_ip_privado(tmp_path) -> None:
    rotas = {"/evil": (302, {"Location": "http://169.254.169.254/latest/"}, b"")}
    with local_server(rotas) as base:
        result = web_fetch.run({"url": base + "/evil"}, make_ctx(tmp_path))
    assert result.ok is False
    assert "recusada" in (result.error or "")
    assert "link-local" in (result.error or "")


def test_fetch_sem_flag_local_e_bloqueado(tmp_path) -> None:
    with local_server({"/": _html(HTML_ARTIGO)}) as base:
        result = web_fetch.run({"url": base + "/"}, make_ctx(tmp_path, allow_local=False))
    assert result.ok is False
    assert "recusada" in (result.error or "")
    assert "loopback" in (result.error or "")


def test_fetch_respeita_limite_de_bytes(tmp_path) -> None:
    corpo = b"A" * 5000
    rotas = {"/grande": (200, {"Content-Type": "text/html"}, corpo)}
    ctx = make_ctx(tmp_path, web={"max_download_bytes": 1024})
    with local_server(rotas) as base:
        result = web_fetch.run({"url": base + "/grande"}, ctx)
    assert result.ok is False
    assert "limite de 1024 bytes" in (result.error or "")


def test_fetch_limite_tambem_sem_content_length(tmp_path) -> None:
    rotas = {
        "/stream": (
            200,
            {"Content-Type": "text/html", "X-No-Length": "1"},
            b"B" * 5000,
        )
    }
    ctx = make_ctx(tmp_path, web={"max_download_bytes": 1024})
    with local_server(rotas) as base:
        result = web_fetch.run({"url": base + "/stream"}, ctx)
    assert result.ok is False
    assert "excede o limite" in (result.error or "")


def test_fetch_trunca_no_max_chars_da_config(tmp_path) -> None:
    ctx = make_ctx(tmp_path, web={"max_chars": 500})
    with local_server({"/longa": _html(LONG_HTML)}) as base:
        result = web_fetch.run({"url": base + "/longa"}, ctx)
    assert result.ok, result.error
    assert result.data["chars"] == 500
    assert len(result.content) < 8000


def test_fetch_arg_max_chars_nao_passa_do_teto(tmp_path) -> None:
    with local_server({"/longa": _html(LONG_HTML)}) as base:
        result = web_fetch.run({"url": base + "/longa", "max_chars": 999_999}, make_ctx(tmp_path))
    assert result.ok, result.error
    assert result.data["chars"] <= 6000


def test_fetch_pagina_vazia_sugere_navegador(tmp_path) -> None:
    with local_server({"/spa": _html(SHELL_HTML)}) as base:
        result = web_fetch.run({"url": base + "/spa"}, make_ctx(tmp_path))
    assert result.ok is False
    assert "browser_open" in (result.error or "")


def test_fetch_binario_sugere_download(tmp_path) -> None:
    pdf = (200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 fake")
    with local_server({"/doc.pdf": pdf}) as base:
        result = web_fetch.run({"url": base + "/doc.pdf"}, make_ctx(tmp_path))
    assert result.ok is False
    assert "web_download" in (result.error or "")
    assert "application/pdf" in (result.error or "")


def test_fetch_erro_http_claro(tmp_path) -> None:
    with local_server({}) as base:
        result = web_fetch.run({"url": base + "/nao-existe"}, make_ctx(tmp_path))
    assert result.ok is False
    assert "HTTP 404" in (result.error or "")


def test_fetch_url_invalida_erro_de_politica(tmp_path) -> None:
    result = web_fetch.run({"url": "nao-e-uma-url"}, make_ctx(tmp_path))
    assert result.ok is False
    assert "recusada" in (result.error or "")


def test_fetch_cadeia_longa_de_redirects(tmp_path) -> None:
    rotas = {f"/r{i}": (302, {"Location": f"/r{i + 1}"}, b"") for i in range(8)}
    rotas["/r8"] = _html(HTML_ARTIGO)
    with local_server(rotas) as base:
        result = web_fetch.run({"url": base + "/r0"}, make_ctx(tmp_path))
    assert result.ok is False
    assert "redirecionamento" in (result.error or "")


def test_links_resolvem_deduplicam_e_filtram(tmp_path) -> None:
    with local_server({"/pag": _html(LINKS_HTML)}) as base:
        result = web_extract_links.run({"url": base + "/pag"}, make_ctx(tmp_path))
    assert result.ok, result.error
    links = result.data["links"]
    assert result.data["count"] == len(links)
    assert links.count(base + "/interno") == 1, "duplicata deve sumir"
    assert base + "/relativa" in links, "relativa vira absoluta"
    assert base + "/interno" in links
    assert "https://exemplo.org/fora" in links
    for ignorado in ("#topo", "javascript:", "mailto:", "ftp:", "tel:"):
        assert not any(ignorado in link for link in links), ignorado
    assert links.index(base + "/interno") < links.index("https://exemplo.org/fora"), (
        "mesmo domínio primeiro"
    )
    assert "Página interna" in result.content
    assert result.content.startswith("AVISO:")


def test_links_max_links_limita(tmp_path) -> None:
    with local_server({"/pag": _html(LINKS_HTML)}) as base:
        result = web_extract_links.run(
            {"url": base + "/pag", "max_links": 2}, make_ctx(tmp_path)
        )
    assert result.ok, result.error
    assert result.data["count"] == 2


def test_fetch_e_links_erro_de_rede_local_sem_flag(tmp_path) -> None:
    ctx = make_ctx(tmp_path, allow_local=False)
    with local_server({"/": _html(HTML_ARTIGO)}) as base:
        fetch_err = web_fetch.run({"url": base + "/"}, ctx)
        links_err = web_extract_links.run({"url": base + "/"}, ctx)
    assert fetch_err.ok is False and links_err.ok is False
    assert "loopback" in (fetch_err.error or "")
    assert "loopback" in (links_err.error or "")
