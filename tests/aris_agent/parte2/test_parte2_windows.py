"""Testes que precisam da API real do Windows (janelas, UIA, clipboard, teclado/mouse).

Pulados por padrão; ative com ``ARIS_TEST_WINDOWS=1`` ou ``-m windows``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.types import ToolContext
from aris_agent.tools import ToolRegistry
from aris_agent.tools import pc as pacote_pc

pytestmark = pytest.mark.windows


def make_ctx(tmp_path: Path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(session_id="s", workdir=tmp_path, config=cfg, cancel=threading.Event())


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    pacote_pc.register(registry)
    return registry


def run(name: str, args: dict, ctx: ToolContext):
    return make_registry().get(name).run(args, ctx)


def _clipboard_backup() -> str | None:
    import win32clipboard
    import win32con

    try:
        win32clipboard.OpenClipboard()
    except Exception:  # noqa: BLE001
        return None
    try:
        try:
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        except Exception:  # noqa: BLE001
            return None
    finally:
        win32clipboard.CloseClipboard()


def _clipboard_restore(value: str | None) -> None:
    if value is None:
        return
    import win32clipboard
    import win32con

    try:
        win32clipboard.OpenClipboard()
    except Exception:  # noqa: BLE001
        return
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, value)
    except Exception:  # noqa: BLE001
        pass
    finally:
        win32clipboard.CloseClipboard()


def test_lista_janelas_reais(tmp_path) -> None:
    result = run("pc_list_windows", {"limit": 20}, make_ctx(tmp_path))
    assert result.ok, result.error
    janelas = result.data["windows"]
    assert janelas, "deve haver ao menos uma janela com título"
    for janela in janelas:
        assert janela["title"]
        assert isinstance(janela["hwnd"], int)
        assert isinstance(janela["pid"], int)
        assert isinstance(janela["active"], bool)


def test_lista_janelas_com_filtro(tmp_path) -> None:
    result = run("pc_list_windows", {"title": "zzz_sem_janela_assim"}, make_ctx(tmp_path))
    assert result.ok
    assert result.data["windows"] == []


def test_clipboard_roundtrip(tmp_path) -> None:
    antigo = _clipboard_backup()
    try:
        ctx = make_ctx(tmp_path)
        texto = "ARIS clipboard çãé"
        escrita = run("pc_clipboard_set", {"text": texto}, ctx)
        assert escrita.ok, escrita.error
        leitura = run("pc_clipboard_get", {}, ctx)
        assert leitura.ok, leitura.error
        assert texto in leitura.content
    finally:
        _clipboard_restore(antigo)


def test_screenshot_salva_png(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    result = run("pc_screenshot", {}, ctx)
    assert result.ok, result.error
    caminho = Path(result.data["path"])
    assert caminho.exists()
    assert caminho.suffix == ".png"
    assert caminho.stat().st_size > 100
    assert result.artifacts == [str(caminho)]
    caminho.unlink(missing_ok=True)


def test_screenshot_nome_dentro_das_raizes(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    result = run("pc_screenshot", {"filename": "cap1.png"}, ctx)
    assert result.ok, result.error
    caminho = Path(result.data["path"])
    # nome relativo resolve no workdir (como nas outras ferramentas de arquivo)
    assert caminho.parent == tmp_path.resolve()
    caminho.unlink(missing_ok=True)


def test_screenshot_fora_das_raizes(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    result = run("pc_screenshot", {"filename": str(tmp_path.parent / "cap.png")}, ctx)
    assert not result.ok
    assert "fora das raízes" in (result.error or "")


def _abrir_notepad():
    pytest.importorskip("pywinauto")
    from pywinauto import Application

    try:
        app = Application(backend="uia").start("notepad.exe")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"não consegui abrir o Bloco de Notas: {exc}")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            janela = app.top_window()
            if janela.window_text():
                return app, janela
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    pytest.skip("Bloco de Notas não abriu a janela a tempo")


def test_notepad_ui_find_type_click_keys_focus(tmp_path) -> None:
    """Fluxo completo numa janela real: achar, digitar, clicar, atalho, foco."""
    app, janela = _abrir_notepad()
    ctx = make_ctx(tmp_path)
    try:
        titulo = janela.window_text()
        assert titulo

        achados = run("pc_ui_find", {"window_title": titulo}, ctx)
        assert achados.ok, achados.error
        tipos = {controle["type"] for controle in achados.data["controls"]}
        assert "Edit" in tipos, f"esperava controle Edit em {tipos}"

        texto = "Olá ARIS çãé!"
        escrita = run(
            "pc_ui_type",
            {"window_title": titulo, "control_type": "Edit", "text": texto},
            ctx,
        )
        assert escrita.ok, escrita.error

        # confirma o texto digitado via ctrl+a / ctrl+c e a área de transferência
        antigo = _clipboard_backup()
        try:
            copiar = run("pc_keys", {"keys": "ctrl+a"}, ctx)
            assert copiar.ok, copiar.error
            copiar = run("pc_keys", {"keys": "ctrl+c"}, ctx)
            assert copiar.ok, copiar.error
            leitura = run("pc_clipboard_get", {}, ctx)
            assert leitura.ok, leitura.error
            assert texto in leitura.content
        finally:
            _clipboard_restore(antigo)

        clique = run("pc_ui_click", {"window_title": titulo, "control_type": "Edit"}, ctx)
        assert clique.ok, clique.error

        foco = run("pc_focus_window", {"title": titulo}, ctx)
        assert foco.ok, foco.error

        digitar = run("pc_ui_type", {"window_title": titulo, "text": "x"}, ctx)
        assert digitar.ok, digitar.error
    finally:
        try:
            app.kill()
        except Exception:  # noqa: BLE001 - melhor esforço de limpeza
            pass


def test_focus_janela_inexistente(tmp_path) -> None:
    result = run("pc_focus_window", {"title": "zzz_sem_janela_assim"}, make_ctx(tmp_path))
    assert not result.ok
    assert "nenhuma janela" in (result.error or "")


def test_mouse_move_e_retorno(tmp_path) -> None:
    pyautogui = pytest.importorskip("pyautogui")
    antes = pyautogui.position()
    destino = (max(1, pyautogui.size()[0] // 2), max(1, pyautogui.size()[1] // 2))
    ctx = make_ctx(tmp_path)
    try:
        result = run("pc_mouse", {"action": "move", "x": destino[0], "y": destino[1]}, ctx)
        if not result.ok and "FailSafe" in (result.error or ""):
            pytest.skip("FAILSAFE do pyautogui ativo (mouse no canto)")
        assert result.ok, result.error
        atual = pyautogui.position()
        assert (atual.x, atual.y) == destino
    finally:
        try:
            pyautogui.moveTo(antes.x, antes.y, duration=0.05)
        except Exception:  # noqa: BLE001
            pass
