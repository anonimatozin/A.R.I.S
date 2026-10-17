"""Testes de pc_open_app (mapa da config; startfile simulado nos testes comuns)."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.types import ToolContext
from aris_agent.tools import ToolRegistry
from aris_agent.tools import pc as pacote_pc


def make_ctx(tmp_path: Path, sections: dict | None = None) -> ToolContext:
    cfg = AgentConfig(
        workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data", sections=sections or {}
    )
    return ToolContext(session_id="s", workdir=tmp_path, config=cfg, cancel=threading.Event())


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    pacote_pc.register(registry)
    return registry


def run(ctx: ToolContext, args: dict):
    return make_registry().get("pc_open_app").run(args, ctx)


def fake_startfile(monkeypatch) -> list[str]:
    chamadas: list[str] = []
    monkeypatch.setattr("os.startfile", lambda alvo: chamadas.append(str(alvo)), raising=False)
    return chamadas


def test_app_nao_cadastrado_explica_como_cadastrar(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    result = run(ctx, {"name": "chrome"})
    assert not result.ok
    assert "não está cadastrado" in (result.error or "")
    assert "aris_agent.json" in (result.error or "")
    assert "apps" in (result.error or "")


def test_app_cadastrado_abre_caminho(tmp_path, monkeypatch) -> None:
    exe = tmp_path / "meuapp.exe"
    exe.write_bytes(b"MZ")
    sections = {"pc": {"apps": {"meuapp": str(exe)}}}
    ctx = make_ctx(tmp_path, sections)
    chamadas = fake_startfile(monkeypatch)
    result = run(ctx, {"name": "MeuApp"})
    assert result.ok, result.error
    assert chamadas == [str(exe)]
    assert result.data["target"] == str(exe)


def test_app_cadastrado_com_uri(tmp_path, monkeypatch) -> None:
    sections = {"pc": {"apps": {"site": "https://exemplo.com/aris"}}}
    ctx = make_ctx(tmp_path, sections)
    chamadas = fake_startfile(monkeypatch)
    result = run(ctx, {"name": "site"})
    assert result.ok, result.error
    assert chamadas == ["https://exemplo.com/aris"]


def test_app_cadastrado_com_uri_de_loja(tmp_path, monkeypatch) -> None:
    sections = {"pc": {"apps": {"config": "ms-settings:display"}}}
    ctx = make_ctx(tmp_path, sections)
    chamadas = fake_startfile(monkeypatch)
    result = run(ctx, {"name": "config"})
    assert result.ok, result.error
    assert chamadas == ["ms-settings:display"]


def test_app_caminho_inexistente_erro(tmp_path) -> None:
    sections = {"pc": {"apps": {"fantasma": str(tmp_path / "nao_existe.exe")}}}
    ctx = make_ctx(tmp_path, sections)
    result = run(ctx, {"name": "fantasma"})
    assert not result.ok
    assert "não existe" in (result.error or "")


def test_app_nao_executa_string_arbitraria(tmp_path, monkeypatch) -> None:
    """name com barra/PATH não vira execução: só sai do mapa ou cai no erro."""
    ctx = make_ctx(tmp_path)
    chamadas = fake_startfile(monkeypatch)
    result = run(ctx, {"name": "../../windows/system32/cmd.exe"})
    assert not result.ok
    assert chamadas == []
    assert "caminho" in (result.error or "")


def test_app_name_vazio(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    assert not run(ctx, {"name": "   "}).ok
    assert not run(ctx, {}).ok


def test_app_store_fallback_abre_loja(tmp_path, monkeypatch) -> None:
    sections = {"pc": {"apps": {}, "store_fallback": True}}
    ctx = make_ctx(tmp_path, sections)
    chamadas = fake_startfile(monkeypatch)
    result = run(ctx, {"name": "meu app raro"})
    assert result.ok, result.error
    assert len(chamadas) == 1
    assert chamadas[0].startswith("ms-windows-store://search/?query=")
    assert "meu%20app%20raro" in chamadas[0]


def test_app_mapa_plano_sem_chave_apps(tmp_path, monkeypatch) -> None:
    """Formato do prompt: seção pc é o próprio mapa {"chrome": caminho}."""
    exe = tmp_path / "n2.exe"
    exe.write_bytes(b"MZ")
    sections = {"pc": {"chrome": str(exe), "run_timeout_s": 15}}
    ctx = make_ctx(tmp_path, sections)
    chamadas = fake_startfile(monkeypatch)
    result = run(ctx, {"name": "chrome"})
    assert result.ok, result.error
    assert chamadas == [str(exe)]


@pytest.mark.skipif(shutil.which("calc.exe") is None, reason="calc.exe fora do PATH")
def test_app_resolve_executavel_do_path(tmp_path, monkeypatch) -> None:
    sections = {"pc": {"apps": {"calculadora": "calc.exe"}}}
    ctx = make_ctx(tmp_path, sections)
    chamadas = fake_startfile(monkeypatch)
    result = run(ctx, {"name": "calculadora"})
    assert result.ok, result.error
    assert len(chamadas) == 1
    assert chamadas[0].lower().endswith("calc.exe")
