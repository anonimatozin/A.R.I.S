"""Testes da CLI da Parte 1 (sem internet: servidor falso e configuração local)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from test_parte1_fake_server import FakeOpenAIServer, completion, tool_call_completion

from aris_agent.llm import cli

PROJETO = Path(__file__).resolve().parents[3]


def write_config(tmp_path, section: dict) -> Path:
    path = tmp_path / "aris_agent.json"
    path.write_text(
        json.dumps({"sections": {"llm": section}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_cli_sem_provedores_explica_como_configurar(tmp_path, capsys) -> None:
    config = write_config(tmp_path, {})
    code = cli.main(["olá", "--config", str(config)])
    saida = capsys.readouterr().out
    assert code == 2
    assert "Nenhum provedor de LLM configurado" in saida
    assert "aris_agent.json" in saida
    assert "chains" in saida
    assert "api_key_env" in saida


def test_cli_config_inexistente(tmp_path, capsys) -> None:
    code = cli.main(["olá", "--config", str(tmp_path / "nao_existe.json")])
    assert code == 2
    assert "não encontrado" in capsys.readouterr().out


def test_cli_chave_ausente_falha_limpo(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("CHAVE_NAO_EXISTE_123", raising=False)
    config = write_config(
        tmp_path,
        {
            "providers": {
                "unico": {
                    "base_url": "http://127.0.0.1:9/v1",
                    "api_key_env": "CHAVE_NAO_EXISTE_123",
                    "models": ["modelo-x"],
                }
            },
            "chains": {"normal": ["unico:modelo-x"]},
        },
    )
    code = cli.main(["olá", "--config", str(config)])
    saida = capsys.readouterr().out
    assert code == 2
    assert "INATIVO" in saida
    assert "CHAVE_NAO_EXISTE_123" in saida
    assert "Nenhum provedor ativo" in saida


def test_cli_conversa_com_servidor_falso(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("CHAVE_CLI_TESTE", "gsk_abc123456789")
    with FakeOpenAIServer() as server:
        server.enqueue(payload=completion("Olá! Sou a A.R.I.S.", usage={"prompt_tokens": 20, "completion_tokens": 9}))
        config = write_config(
            tmp_path,
            {
                "providers": {
                    "falso": {
                        "base_url": server.base_url,
                        "api_key_env": "CHAVE_CLI_TESTE",
                        "models": ["modelo-teste"],
                    }
                },
                "chains": {"normal": ["falso:modelo-teste"]},
            },
        )
        code = cli.main(
            ["olá", "--config", str(config), "--difficulty", "normal", "--stats"]
        )
        capturado = server.requests[0]

    saida = capsys.readouterr().out
    assert code == 0, saida
    assert "Olá! Sou a A.R.I.S." in saida
    assert "[falso:modelo-teste]" in saida
    assert "tokens=20+9=29" in saida
    assert '"limits"' in saida  # --stats
    assert capturado["body"]["messages"][-1]["content"] == "olá"
    assert capturado["headers"].get("Authorization") == "Bearer gsk_abc123456789"


def test_cli_tools_demo_chama_a_ferramenta(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("CHAVE_CLI_TESTE", "gsk_abc123456789")
    with FakeOpenAIServer() as server:
        server.enqueue(payload=tool_call_completion("soma", '{"a": 2, "b": 3}'))
        config = write_config(
            tmp_path,
            {
                "providers": {
                    "falso": {
                        "base_url": server.base_url,
                        "api_key_env": "CHAVE_CLI_TESTE",
                        "models": ["modelo-teste"],
                    }
                },
                "chains": {"normal": ["falso:modelo-teste"]},
            },
        )
        code = cli.main(["soma 2 e 3", "--config", str(config), "--tools-demo"])

    saida = capsys.readouterr().out
    assert code == 0, saida
    assert "[chamada de ferramenta] soma(" in saida
    assert '"a": 2' in saida and '"b": 3' in saida
    assert "ok: o modelo chamou a ferramenta" in saida


def test_cli_tools_demo_sem_chamada_falha(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("CHAVE_CLI_TESTE", "gsk_abc123456789")
    with FakeOpenAIServer() as server:
        server.enqueue(payload=completion("não vou chamar ferramenta"))
        config = write_config(
            tmp_path,
            {
                "providers": {
                    "falso": {
                        "base_url": server.base_url,
                        "api_key_env": "CHAVE_CLI_TESTE",
                        "models": ["modelo-teste"],
                    }
                },
                "chains": {"normal": ["falso:modelo-teste"]},
            },
        )
        code = cli.main(["oi", "--config", str(config), "--tools-demo"])

    saida = capsys.readouterr().out
    assert code == 1
    assert "NÃO chamou a ferramenta" in saida


def test_cli_provider_restringe_a_cadeia(tmp_path, capsys) -> None:
    with FakeOpenAIServer() as server_a, FakeOpenAIServer() as server_b:
        server_a.enqueue(payload=completion("deveria ser ignorado"))
        server_b.enqueue(payload=completion("resposta do b"))
        config = write_config(
            tmp_path,
            {
                "providers": {
                    "primario": {"base_url": server_a.base_url, "models": ["ma"]},
                    "secundario": {"base_url": server_b.base_url, "models": ["mb"]},
                },
                "chains": {"normal": ["primario:ma", "secundario:mb"]},
            },
        )
        code = cli.main(
            ["olá", "--config", str(config), "--provider", "secundario"]
        )
        assert server_a.request_count == 0
        assert server_b.request_count == 1

    saida = capsys.readouterr().out
    assert code == 0
    assert "resposta do b" in saida


def test_cli_provider_desconhecido(tmp_path, capsys) -> None:
    config = write_config(
        tmp_path,
        {"providers": {"x": {"base_url": "http://x/v1", "models": ["m"]}}},
    )
    code = cli.main(["olá", "--config", str(config), "--provider", "nao_existe"])
    assert code == 2
    assert "provedor desconhecido" in capsys.readouterr().out


def test_modulo_executavel_com_python_m(tmp_path) -> None:
    # config sem provedores → exit 2 explicativo, sem tocar na rede
    caminho = tmp_path / "aris_agent.json"
    caminho.write_text(json.dumps({"sections": {"llm": {}}}), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "aris_agent.llm.cli",
            "olá",
            "--config",
            str(caminho),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(PROJETO),
        env={**os.environ},
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Nenhum provedor de LLM configurado" in proc.stdout
