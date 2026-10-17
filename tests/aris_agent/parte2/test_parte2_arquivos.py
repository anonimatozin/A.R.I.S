"""Testes das ferramentas de arquivo da Parte 2 (comuns, só em tmp_path)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.types import ToolContext
from aris_agent.tools import ToolRegistry
from aris_agent.tools import pc as pacote_pc
from aris_agent.tools.pc import files as modulo_files


def make_ctx(tmp_path: Path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(session_id="s", workdir=tmp_path, config=cfg, cancel=threading.Event())


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    pacote_pc.register(registry)
    return registry


def run(registry: ToolRegistry, name: str, args: dict, ctx: ToolContext):
    return registry.get(name).run(args, ctx)


def test_list_dir_mostra_tamanho_e_data(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "lista").mkdir()
    (tmp_path / "lista" / "pasta").mkdir()
    (tmp_path / "lista" / "arquivo.txt").write_text("abc", encoding="utf-8")
    result = run(reg, "pc_list_dir", {"path": "lista"}, ctx)
    assert result.ok, result.error
    assert "[D] pasta/" in result.content
    assert "[F] arquivo.txt" in result.content
    assert "3 B" in result.content
    assert result.data["total"] == 2


def test_list_dir_respeita_limit(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "lista").mkdir()
    for index in range(10):
        (tmp_path / "lista" / f"f{index}.txt").write_text("x", encoding="utf-8")
    result = run(reg, "pc_list_dir", {"path": "lista", "limit": 4}, ctx)
    assert result.ok
    assert result.data["shown"] == 4
    assert "mais 6 item(ns) omitidos" in result.content


def test_list_dir_caminho_inexistente(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_list_dir", {"path": "nao_existe"}, ctx)
    assert not result.ok
    assert "não existe" in (result.error or "")


def test_list_dir_em_arquivo_erro(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "x.txt").write_text("a", encoding="utf-8")
    result = run(reg, "pc_list_dir", {"path": "x.txt"}, ctx)
    assert not result.ok
    assert "pasta" in (result.error or "")


def test_read_file_utf8_e_offset_limit(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    alvo = tmp_path / "texto.txt"
    alvo.write_text("um\ndois\ntrês\nquatro", encoding="utf-8")
    result = run(reg, "pc_read_file", {"path": "texto.txt"}, ctx)
    assert result.ok, result.error
    assert "um" in result.content and "quatro" in result.content
    parcial = run(reg, "pc_read_file", {"path": "texto.txt", "offset": 2, "limit": 1}, ctx)
    assert parcial.ok
    assert "2 | dois" in parcial.content
    assert "1 | um" not in parcial.content


def test_read_file_detecta_cp1252(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    alvo = tmp_path / "antigo.txt"
    alvo.write_bytes("açãção ç".encode("cp1252"))
    result = run(reg, "pc_read_file", {"path": "antigo.txt"}, ctx)
    assert result.ok, result.error
    assert "açãção" in result.content


def test_read_file_avisa_binario(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    alvo = tmp_path / "dados.bin"
    alvo.write_bytes(b"\x00\x01\x02\x03resto")
    result = run(reg, "pc_read_file", {"path": "dados.bin"}, ctx)
    assert result.ok
    assert "binário" in result.content
    assert result.data["binary"] is True


def test_read_file_trunca_saida_com_marcador(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    alvo = tmp_path / "grande.txt"
    alvo.write_text("\n".join(f"linha {i:04d} " + "x" * 80 for i in range(400)), encoding="utf-8")
    result = run(reg, "pc_read_file", {"path": "grande.txt"}, ctx)
    assert result.ok
    assert "caracteres omitidos" in result.content
    assert len(result.content) < 9000


def test_read_file_offset_apos_fim_do_arquivo(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    alvo = tmp_path / "linhas.txt"
    alvo.write_text("\n".join(str(i) for i in range(20)), encoding="utf-8")
    result = run(reg, "pc_read_file", {"path": "linhas.txt", "offset": 999}, ctx)
    assert result.ok
    assert "nenhuma linha" in result.content


def test_write_file_cria_pasta_pai(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_write_file", {"path": "sub/pasta/novo.txt", "content": "oi"}, ctx)
    assert result.ok, result.error
    assert (tmp_path / "sub" / "pasta" / "novo.txt").read_text(encoding="utf-8") == "oi"
    assert result.artifacts == [str(tmp_path / "sub" / "pasta" / "novo.txt")]


def test_write_file_faz_backup_bak_na_sobrescrita(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    alvo = tmp_path / "doc.txt"
    alvo.write_text("conteúdo original", encoding="utf-8")
    result = run(reg, "pc_write_file", {"path": "doc.txt", "content": "novo"}, ctx)
    assert result.ok, result.error
    backups = list(tmp_path.glob("doc.txt.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "conteúdo original"
    assert alvo.read_text(encoding="utf-8") == "novo"
    assert result.data["backup"] is not None


def test_write_file_sem_backup_quando_false(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "doc.txt").write_text("velho", encoding="utf-8")
    result = run(reg, "pc_write_file", {"path": "doc.txt", "content": "novo", "backup": False}, ctx)
    assert result.ok
    assert list(tmp_path.glob("*.bak")) == []
    assert result.data["backup"] is None


def test_write_file_sem_content_erro(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_write_file", {"path": "a.txt"}, ctx)
    assert not result.ok
    assert "content" in (result.error or "")


def test_move_file_renomeia(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "antes.txt").write_text("x", encoding="utf-8")
    result = run(reg, "pc_move_file", {"source": "antes.txt", "destination": "depois.txt"}, ctx)
    assert result.ok, result.error
    assert not (tmp_path / "antes.txt").exists()
    assert (tmp_path / "depois.txt").read_text(encoding="utf-8") == "x"


def test_move_file_nao_sobrescreve_sem_overwrite(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    result = run(reg, "pc_move_file", {"source": "a.txt", "destination": "b.txt"}, ctx)
    assert not result.ok
    assert "já existe" in (result.error or "")
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "b"


def test_move_file_com_overwrite_substitui(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    result = run(
        reg, "pc_move_file", {"source": "a.txt", "destination": "b.txt", "overwrite": True}, ctx
    )
    assert result.ok, result.error
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "a"


def test_delete_file_usa_send2trash_simulado(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    alvo = tmp_path / "lixo.txt"
    alvo.write_text("apagável", encoding="utf-8")
    chamadas: list[str] = []

    def fake_send2trash(caminho: str) -> None:
        chamadas.append(caminho)

    monkeypatch.setattr(modulo_files, "send2trash", fake_send2trash)
    result = run(reg, "pc_delete_file", {"path": "lixo.txt"}, ctx)
    assert result.ok, result.error
    assert chamadas == [str(alvo.resolve())]
    assert alvo.exists(), "a ferramenta não deve apagar permanentemente"


def test_delete_file_sem_dependencia(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(modulo_files, "send2trash", None)
    result = run(reg, "pc_delete_file", {"path": "x.txt"}, ctx)
    assert not result.ok
    assert "send2trash" in (result.error or "")


def test_delete_file_recusa_raiz_permitida(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_delete_file", {"path": "ws"}, ctx)
    assert not result.ok
    assert "raiz" in (result.error or "")


def test_traversal_escape_de_raiz_recusado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    alvo = tmp_path.parent / "fora.txt"
    alvo.write_text("segredo", encoding="utf-8")
    try:
        result = run(reg, "pc_read_file", {"path": str(alvo)}, ctx)
        assert not result.ok
        assert "fora das raízes" in (result.error or "")
        assert str(alvo.resolve()) in (result.error or "")
    finally:
        alvo.unlink(missing_ok=True)


def test_traversal_ponto_ponto_recusado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_list_dir", {"path": "../nao_existe"}, ctx)
    assert not result.ok
    assert "fora das raízes" in (result.error or "")


def test_caminho_unc_recusado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_read_file", {"path": r"\\servidor\compartilhado\x.txt"}, ctx)
    assert not result.ok
    assert "UNC" in (result.error or "")


@pytest.mark.windows  # "C:arquivo.txt" relativo a unidade: noção de drive do Windows
def test_caminho_relativo_a_unidade_recusado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_read_file", {"path": "C:pasta\\x.txt"}, ctx)
    assert not result.ok
    assert "unidade" in (result.error or "")


def test_link_simbolico_para_fora_recusado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    alvo = tmp_path.parent / "alvo_fora.txt"
    alvo.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(alvo)
    except OSError:
        alvo.unlink(missing_ok=True)
        pytest.skip("symlink exige privilégio/Developer Mode no Windows")
    try:
        result = run(reg, "pc_read_file", {"path": "link.txt"}, ctx)
        assert not result.ok
        assert "fora das raízes" in (result.error or "")
    finally:
        link.unlink(missing_ok=True)
        alvo.unlink(missing_ok=True)


def test_read_fora_das_raizes_com_caminho_relativo_completo(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_write_file", {"path": "../../escapou.txt", "content": "x"}, ctx)
    assert not result.ok
    assert "fora das raízes" in (result.error or "")


def test_search_files_por_nome(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "sub" / "b.py").write_text("print(2)", encoding="utf-8")
    (tmp_path / "c.txt").write_text("texto", encoding="utf-8")
    result = run(reg, "pc_search_files", {"root": ".", "pattern": "*.py"}, ctx)
    assert result.ok, result.error
    paths = {item["path"] for item in result.data["results"]}
    assert paths == {"a.py", str(Path("sub") / "b.py")}


def test_search_files_por_conteudo(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "hit.txt").write_text("AQUI tem a palavra secreta", encoding="utf-8")
    (tmp_path / "miss.txt").write_text("nada demais", encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\x00secreta")
    result = run(reg, "pc_search_files", {"root": ".", "contains": "SECRETA"}, ctx)
    assert result.ok, result.error
    paths = [item["path"] for item in result.data["results"]]
    assert paths == ["hit.txt"]
    assert "AQUI tem a palavra" in result.content


def test_search_files_limita_resultados(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    for index in range(10):
        (tmp_path / f"m{index}.md").write_text("x", encoding="utf-8")
    result = run(reg, "pc_search_files", {"root": ".", "pattern": "*.md", "max_results": 3}, ctx)
    assert result.ok
    assert len(result.data["results"]) == 3
    assert "limite" in result.content


def test_search_files_sem_resultado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_search_files", {"root": ".", "pattern": "*.zzz"}, ctx)
    assert result.ok
    assert "Nenhum resultado" in result.content
