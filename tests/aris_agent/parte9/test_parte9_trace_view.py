"""Parte 9 — visualizador de traces em HTML (offline, arquivo único)."""

from __future__ import annotations

from aris_agent.evals.trace_view import gerar_html, main

REGISTROS = [
    {"evento": "inicio", "ts": 1700000000.1, "entrada": "bom dia"},
    {"evento": "tool_call", "ts": 1700000000.5, "name": "calc",
     "arguments": {"expression": "2+2"}},
    {"evento": "tool_result", "ts": 1700000000.6, "name": "calc", "ok": True},
    {"evento": "fim", "ts": 1700000001.0, "api_key": "sk-abc123secret"},
]


def test_html_unico_sem_recursos_externos() -> None:
    html = gerar_html([("demo.jsonl", REGISTROS)])
    assert html.startswith("<!DOCTYPE html>")
    assert 'src="http' not in html and "src='http" not in html
    assert 'href="http' not in html and "href='http" not in html
    assert "<style>" in html and "<script>" in html


def test_linha_do_tempo_com_busca_e_tipos() -> None:
    html = gerar_html([("demo.jsonl", REGISTROS)])
    assert 'id="busca"' in html
    assert 'id="tipo"' in html
    assert 'data-tipo="tool_call"' in html
    assert "4 eventos" in html


def test_segredos_redigidos() -> None:
    html = gerar_html([("demo.jsonl", REGISTROS)])
    assert "sk-abc123secret" not in html
    assert "[REDACTED]" in html


def test_cli_grava_arquivo(tmp_path) -> None:
    trace = tmp_path / "t.jsonl"
    trace.write_text(
        '{"evento": "inicio", "ts": 1.0}\n{"evento": "fim", "ts": 2.0}\n',
        encoding="utf-8",
    )
    saida = tmp_path / "traces.html"
    assert main([str(trace), "--out", str(saida)]) == 0
    assert saida.is_file()
    assert "linha do tempo" in saida.read_text(encoding="utf-8")


def test_cli_arquivo_inexistente(tmp_path) -> None:
    assert main([str(tmp_path / "nao-existe.jsonl")]) == 2
