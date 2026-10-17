"""Parte 3: web_download — grava com segurança em workspace/downloads (nunca executa)."""

from __future__ import annotations

from pathlib import Path

from test_parte3_utils import local_server, make_ctx

from aris_agent.tools.web.pages import web_download

CONTEUDO = b"linha1\nlinha2\nconteudo do arquivo de teste\n"


def _txt(content_type: str = "text/plain; charset=utf-8") -> tuple[int, dict, bytes]:
    return 200, {"Content-Type": content_type}, CONTEUDO


def test_download_grava_em_workspace_downloads(tmp_path) -> None:
    with local_server({"/arquivo.txt": _txt()}) as base:
        result = web_download.run({"url": base + "/arquivo.txt"}, make_ctx(tmp_path))
    assert result.ok, result.error
    caminho = Path(result.data["path"])
    assert caminho.exists()
    assert caminho.parent.name == "downloads"
    assert caminho.parent == Path(tmp_path) / "ws" / "downloads"
    assert caminho.read_bytes() == CONTEUDO, "bytes idênticos aos servidos"
    assert result.data["bytes"] == len(CONTEUDO)
    assert result.data["content_type"].startswith("text/plain")
    assert result.artifacts == [str(caminho)]
    assert "Arquivo salvo em:" in result.content
    assert "AVISO:" in result.content, "saída deve ser wrap_untrusted"


def test_download_nome_hostil_e_sanitizado(tmp_path) -> None:
    with local_server({"/qualquer": _txt()}) as base:
        for nome in ("../../../evil name!.exe", "..\\..\\pasta\\truco.bat", ".."):
            result = web_download.run(
                {"url": base + "/qualquer", "filename": nome}, make_ctx(tmp_path)
            )
            assert result.ok, result.error
            caminho = Path(result.data["path"])
            downloads = Path(tmp_path) / "ws" / "downloads"
            assert caminho.parent == downloads, "nunca sai do diretório de downloads"
            assert ".." not in caminho.name
            assert "/" not in caminho.name and "\\" not in caminho.name


def test_download_adiciona_extensao_pelo_tipo(tmp_path) -> None:
    with local_server({"/semnome": _txt("application/json")}) as base:
        result = web_download.run({"url": base + "/semnome"}, make_ctx(tmp_path))
    assert result.ok, result.error
    assert result.data["path"].endswith("semnome.json")


def test_download_nome_repetido_nao_sobrescreve(tmp_path) -> None:
    with local_server({"/arquivo.txt": _txt()}) as base:
        url = base + "/arquivo.txt"
        um = web_download.run({"url": url}, make_ctx(tmp_path))
        dois = web_download.run({"url": url}, make_ctx(tmp_path))
    assert um.ok and dois.ok
    assert um.data["path"] != dois.data["path"]
    assert Path(um.data["path"]).exists() and Path(dois.data["path"]).exists()


def test_download_respeita_limite_de_bytes(tmp_path) -> None:
    rotas = {"/grande.bin": (200, {"Content-Type": "application/octet-stream"}, b"A" * 5000)}
    ctx = make_ctx(tmp_path, web={"max_download_bytes": 1024})
    with local_server(rotas) as base:
        result = web_download.run({"url": base + "/grande.bin"}, ctx)
    assert result.ok is False
    assert "limite" in (result.error or "")
    downloads = Path(tmp_path) / "ws" / "downloads"
    assert not downloads.exists() or not any(downloads.iterdir()), "nada deve ser gravado"


def test_download_arquivo_binario_grava_sem_executar(tmp_path) -> None:
    pdf = b"%PDF-1.4\n% fake pdf\n"
    rotas = {"/doc.pdf": (200, {"Content-Type": "application/pdf"}, pdf)}
    with local_server(rotas) as base:
        result = web_download.run({"url": base + "/doc.pdf"}, make_ctx(tmp_path))
    assert result.ok, result.error
    caminho = Path(result.data["path"])
    assert caminho.suffix == ".pdf"
    assert caminho.read_bytes() == pdf
    assert caminho.name.lower() == "doc.pdf"


def test_download_url_bloqueada(tmp_path) -> None:
    result = web_download.run(
        {"url": "http://169.254.169.254/latest/meta-data/"}, make_ctx(tmp_path)
    )
    assert result.ok is False
    assert "recusada" in (result.error or "")


def test_download_rede_local_sem_flag(tmp_path) -> None:
    with local_server({"/a.txt": _txt()}) as base:
        result = web_download.run({"url": base + "/a.txt"}, make_ctx(tmp_path, allow_local=False))
    assert result.ok is False
    assert "loopback" in (result.error or "")


def test_download_url_invalida(tmp_path) -> None:
    result = web_download.run({"url": "ftp://exemplo.com/a.zip"}, make_ctx(tmp_path))
    assert result.ok is False
    assert "recusada" in (result.error or "")
