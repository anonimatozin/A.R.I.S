"""Validações de UI/teclado/mouse que não tocam na interface (comuns, com guarda de dependência)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.types import ToolContext
from aris_agent.tools import ToolRegistry
from aris_agent.tools import pc as pacote_pc
from aris_agent.tools.pc import input_tools as modulo_input
from aris_agent.tools.pc import ui as modulo_ui


def make_ctx(tmp_path: Path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(session_id="s", workdir=tmp_path, config=cfg, cancel=threading.Event())


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    pacote_pc.register(registry)
    return registry


def run(name: str, args: dict, ctx: ToolContext):
    return make_registry().get(name).run(args, ctx)


needs_pywinauto = pytest.mark.skipif(modulo_ui.Desktop is None, reason="pywinauto indisponível")
needs_pyautogui = pytest.mark.skipif(
    modulo_input.pyautogui is None, reason="pyautogui indisponível"
)


@needs_pywinauto
def test_ui_find_sem_titulo(tmp_path) -> None:
    result = run("pc_ui_find", {}, make_ctx(tmp_path))
    assert not result.ok
    assert "window_title" in (result.error or "")


@needs_pywinauto
def test_ui_find_janela_inexistente(tmp_path) -> None:
    result = run(
        "pc_ui_find", {"window_title": "zzz_titulo_impossivel_zzz"}, make_ctx(tmp_path)
    )
    assert not result.ok
    assert "nenhuma janela" in (result.error or "")


@needs_pywinauto
def test_ui_click_sem_filtros(tmp_path) -> None:
    result = run("pc_ui_click", {"window_title": "x"}, make_ctx(tmp_path))
    assert not result.ok
    assert "control_name" in (result.error or "")


@needs_pywinauto
def test_ui_click_sem_titulo(tmp_path) -> None:
    result = run("pc_ui_click", {"control_type": "Edit"}, make_ctx(tmp_path))
    assert not result.ok
    assert "window_title" in (result.error or "")


@needs_pywinauto
def test_ui_type_texto_nao_string(tmp_path) -> None:
    result = run("pc_ui_type", {"window_title": "x", "text": 123}, make_ctx(tmp_path))
    assert not result.ok
    assert "text" in (result.error or "")


@needs_pyautogui
def test_keys_tecla_invalida(tmp_path) -> None:
    result = run("pc_keys", {"keys": "ctrl+teclaqueexiste"}, make_ctx(tmp_path))
    assert not result.ok
    assert "tecla inválida" in (result.error or "")


@needs_pyautogui
def test_keys_vazio(tmp_path) -> None:
    assert not run("pc_keys", {"keys": "  "}, make_ctx(tmp_path)).ok
    assert not run("pc_keys", {}, make_ctx(tmp_path)).ok


@needs_pyautogui
def test_keys_muitos_atalhos(tmp_path) -> None:
    result = run("pc_keys", {"keys": ", ".join(["ctrl+s"] * 9)}, make_ctx(tmp_path))
    assert not result.ok
    assert "muitos atalhos" in (result.error or "")


@needs_pyautogui
def test_keys_muitas_teclas_no_atalho(tmp_path) -> None:
    result = run("pc_keys", {"keys": "+".join(["ctrl"] * 8)}, make_ctx(tmp_path))
    assert not result.ok
    assert "atalho inválido" in (result.error or "")


def test_mouse_action_invalida(tmp_path) -> None:
    result = run("pc_mouse", {"action": "voar", "x": 1, "y": 1}, make_ctx(tmp_path))
    assert not result.ok
    assert "action" in (result.error or "")


def test_mouse_coordenadas_negativas(tmp_path) -> None:
    result = run("pc_mouse", {"action": "click", "x": -5, "y": 10}, make_ctx(tmp_path))
    assert not result.ok
    assert "coordenadas" in (result.error or "")


@needs_pyautogui
def test_mouse_fora_da_tela(tmp_path) -> None:
    largura, altura = modulo_input.pyautogui.size()
    result = run(
        "pc_mouse", {"action": "move", "x": largura + 500, "y": altura + 500}, make_ctx(tmp_path)
    )
    assert not result.ok
    assert "fora da tela" in (result.error or "")


def test_mouse_sem_dependencia(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(modulo_input, "pyautogui", None)
    # action inválida ainda é barrada antes da dependência
    assert not run("pc_mouse", {"action": "x", "x": 1, "y": 1}, make_ctx(tmp_path)).ok
    # com action válida, o erro é da dependência
    result = run("pc_mouse", {"action": "move", "x": 1, "y": 1}, make_ctx(tmp_path))
    assert not result.ok
    assert "pyautogui" in (result.error or "")
