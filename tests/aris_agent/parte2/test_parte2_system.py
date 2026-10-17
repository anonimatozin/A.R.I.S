"""Testes de pc_system_info e pc_list_processes (psutil, comuns)."""

from __future__ import annotations

import threading
from pathlib import Path

from aris_agent.config import AgentConfig
from aris_agent.contract.types import ToolContext
from aris_agent.tools import ToolRegistry
from aris_agent.tools import pc as pacote_pc
from aris_agent.tools.pc import system as modulo_system


def make_ctx(tmp_path: Path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(session_id="s", workdir=tmp_path, config=cfg, cancel=threading.Event())


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    pacote_pc.register(registry)
    return registry


def test_system_info_basico(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    result = make_registry().get("pc_system_info").run({}, ctx)
    assert result.ok, result.error
    assert "CPU:" in result.content
    assert "RAM:" in result.content
    assert "Disco" in result.content
    assert "Bateria" in result.content
    assert "Tempo ligado" in result.content
    assert result.data["mem_total"] > 0
    assert result.data["cpu_count_logical"] >= 1
    assert "uptime_s" in result.data


def test_system_info_cancelado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    ctx.cancel.set()
    result = make_registry().get("pc_system_info").run({}, ctx)
    assert not result.ok
    assert "cancelado" in (result.error or "")


def test_system_info_sem_psutil(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    monkeypatch.setattr(modulo_system, "psutil", None)
    result = make_registry().get("pc_system_info").run({}, ctx)
    assert not result.ok
    assert "psutil" in (result.error or "")


def test_list_processes_limita_e_ordena(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    result = make_registry().get("pc_list_processes").run({"limit": 5, "sort": "mem"}, ctx)
    assert result.ok, result.error
    processos = result.data["processes"]
    assert 0 < len(processos) <= 5
    rams = [processo["rss"] for processo in processos]
    assert rams == sorted(rams, reverse=True)
    assert "PID" in result.content


def test_list_processes_filtro_por_nome(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    result = make_registry().get("pc_list_processes").run({"name": "python", "limit": 50}, ctx)
    assert result.ok, result.error
    processos = result.data["processes"]
    assert processos, "o próprio pytest roda em python.exe"
    for processo in processos:
        assert "python" in processo["name"].lower()


def test_list_processes_sem_resultado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    result = make_registry().get("pc_list_processes").run({"name": "zzz_nome_impossivel"}, ctx)
    assert result.ok
    assert "Nenhum processo" in result.content
    assert result.data["processes"] == []


def test_list_processes_sem_psutil(tmp_path, monkeypatch) -> None:
    ctx = make_ctx(tmp_path)
    monkeypatch.setattr(modulo_system, "psutil", None)
    result = make_registry().get("pc_list_processes").run({}, ctx)
    assert not result.ok
    assert "psutil" in (result.error or "")
