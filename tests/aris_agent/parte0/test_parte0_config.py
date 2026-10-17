"""Testes da configuração do agente (Parte 0)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig, load_config


@pytest.fixture(autouse=True)
def _env_limpo(monkeypatch) -> None:
    """Isola os testes das variáveis ARIS_AGENT_* do ambiente real."""
    for key in list(os.environ):
        if key.startswith("ARIS_AGENT_"):
            monkeypatch.delenv(key, raising=False)


def _escreve_json(path: Path, dados: dict) -> Path:
    path.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_load_sem_json_usa_padroes(tmp_path) -> None:
    cfg = load_config(tmp_path / "nao_existe.json")
    assert cfg.max_steps == 12
    assert cfg.max_tool_chars == 8000
    assert cfg.max_total_tokens_per_task == 60000
    assert cfg.confirm_timeout_s == 30.0
    assert cfg.agent_enabled is False
    assert cfg.sections == {}
    assert cfg.section("llm") == {}
    assert cfg.section("qualquer_coisa") == {}
    assert cfg.allowed_roots == [cfg.workspace_dir]
    assert cfg.audit_log_path == cfg.data_dir / "audit.jsonl"
    assert cfg.workspace_dir.is_dir() and cfg.data_dir.is_dir()


def test_load_com_json(tmp_path) -> None:
    dados = {
        "workspace_dir": str(tmp_path / "ws"),
        "data_dir": str(tmp_path / "dados"),
        "allowed_roots": [str(tmp_path / "ws"), str(tmp_path / "outro")],
        "max_steps": 7,
        "confirm_timeout_s": 5.5,
        "agent_enabled": True,
        "sections": {
            "llm": {"chains": {"easy": ["exemplo:demo"]}},
            "pc": {"apps": {"chrome": "C:/chrome.exe"}},
        },
    }
    caminho = _escreve_json(tmp_path / "aris_agent.json", dados)
    cfg = load_config(caminho)

    assert cfg.workspace_dir == tmp_path / "ws"
    assert cfg.data_dir == tmp_path / "dados"
    assert cfg.allowed_roots == [tmp_path / "ws", tmp_path / "outro"]
    assert cfg.max_steps == 7
    assert cfg.confirm_timeout_s == 5.5
    assert cfg.agent_enabled is True
    assert cfg.section("llm")["chains"]["easy"] == ["exemplo:demo"]
    assert cfg.section("pc")["apps"]["chrome"] == "C:/chrome.exe"
    assert cfg.section("web") == {}
    assert (tmp_path / "ws").is_dir()
    assert (tmp_path / "dados").is_dir()


def test_json_com_credencial_e_removida(tmp_path, caplog) -> None:
    dados = {
        "sections": {
            "llm": {
                "base_url": "https://exemplo.com/v1",
                "api_key": "sk-NAOPODEESTARAQUI",
                "token": "abc",
            }
        }
    }
    caminho = _escreve_json(tmp_path / "aris_agent.json", dados)
    cfg = load_config(caminho)

    assert cfg.section("llm") == {"base_url": "https://exemplo.com/v1"}
    texto = json.dumps(cfg.to_dict())
    assert "sk-NAOPODEESTARAQUI" not in texto
    assert any("credencial" in r.getMessage() for r in caplog.records)


def test_variavel_de_ambiente_vence_json(tmp_path, monkeypatch) -> None:
    dados = {"max_steps": 7, "agent_enabled": False, "workspace_dir": str(tmp_path / "ws1")}
    caminho = _escreve_json(tmp_path / "aris_agent.json", dados)
    monkeypatch.setenv("ARIS_AGENT_MAX_STEPS", "3")
    monkeypatch.setenv("ARIS_AGENT_AGENT_ENABLED", "1")
    monkeypatch.setenv("ARIS_AGENT_WORKSPACE_DIR", str(tmp_path / "ws2"))

    cfg = load_config(caminho)
    assert cfg.max_steps == 3
    assert cfg.agent_enabled is True
    assert cfg.workspace_dir == tmp_path / "ws2"
    # sections continuam só no JSON
    assert cfg.sections == {}


def test_allowed_roots_por_variavel(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARIS_AGENT_ALLOWED_ROOTS", f"{tmp_path / 'a'}{os.pathsep}{tmp_path / 'b'}")
    cfg = load_config(tmp_path / "nao_existe.json")
    assert cfg.allowed_roots == [tmp_path / "a", tmp_path / "b"]


def test_json_invalido_cai_nos_padroes(tmp_path, caplog) -> None:
    caminho = tmp_path / "aris_agent.json"
    caminho.write_text("{isso não é json", encoding="utf-8")
    cfg = load_config(caminho)
    assert cfg.max_steps == 12
    assert cfg.sections == {}
    assert any("ignorando" in r.getMessage() for r in caplog.records)


def test_sections_nao_dict_ignoradas(tmp_path, caplog) -> None:
    caminho = _escreve_json(tmp_path / "aris_agent.json", {"sections": {"llm": 3, "pc": {}}})
    cfg = load_config(caminho)
    assert cfg.section("pc") == {}
    assert cfg.section("llm") == {}
    assert any("não é objeto" in r.getMessage() for r in caplog.records)


def test_to_dict_serializavel(tmp_path) -> None:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    texto = json.dumps(cfg.to_dict())
    assert "workspace_dir" in texto
    cfg2 = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    assert cfg2.allowed_roots == [tmp_path / "ws"]


def test_variavel_ruim_de_numero_e_ignorada(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("ARIS_AGENT_MAX_STEPS", "grande")
    cfg = load_config(tmp_path / "nao_existe.json")
    assert cfg.max_steps == 12
    assert any("não é um inteiro" in r.getMessage() for r in caplog.records)
