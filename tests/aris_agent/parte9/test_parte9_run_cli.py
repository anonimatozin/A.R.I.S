"""Parte 9 — CLI de avaliação (``python -m aris_agent.evals.run``)."""

from __future__ import annotations

import json

from aris_agent.evals.run import main


def test_intents_sai_zero_com_meta_atingida(capsys) -> None:
    assert main(["--intents"]) == 0
    saida = capsys.readouterr().out
    assert "classificador de intenções" in saida


def test_filtro_com_formato_errado_rejeitado() -> None:
    assert main(["--filter", "categoria invalida"]) == 2


def test_execucao_roteirizada_filtrada(tmp_path, capsys) -> None:
    codigo = main(["--filter", "categoria=conversa", "--out", str(tmp_path)])
    assert codigo == 0, capsys.readouterr().out

    json_path = tmp_path / "avaliacao_scripted.json"
    md_path = tmp_path / "avaliacao_scripted.md"
    assert json_path.is_file() and md_path.is_file()

    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["modo"] == "scripted"
    assert report["categorias"]["conversa"]["taxa"] == 1.0
    assert set(report["categorias"]) == {"conversa"}
    assert "100.0%" in md_path.read_text(encoding="utf-8")
