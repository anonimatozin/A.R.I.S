"""Área de transferência (pywin32 com fallback para tkinter)."""

from __future__ import annotations

import logging
import time

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import err, guarded, ok_result, out, schema

log = logging.getLogger("aris.agent.tools.pc.clipboard")

try:
    import win32clipboard
    import win32con
except ImportError:  # pragma: no cover - só existe no Windows
    win32clipboard = None  # type: ignore[assignment]
    win32con = None  # type: ignore[assignment]

_MAX_CLIPBOARD_CHARS = 200_000

SPEC_CLIPBOARD_GET = ToolSpec(
    name="pc_clipboard_get",
    description="Lê o texto atual da área de transferência.",
    parameters=schema({}),
    risk=Risk.READ,
    untrusted_output=True,
    tags=("pc", "clipboard"),
    timeout_s=10.0,
)

SPEC_CLIPBOARD_SET = ToolSpec(
    name="pc_clipboard_set",
    description="Coloca texto na área de transferência (substitui o conteúdo atual).",
    parameters=schema(
        {
            "text": {"type": "string", "description": "Texto a copiar."},
            "clear": {
                "type": "boolean",
                "description": "Limpar antes de escrever (padrão true).",
            },
        },
        required=("text",),
    ),
    risk=Risk.WRITE,
    tags=("pc", "clipboard"),
    timeout_s=10.0,
)


def _open_with_retry() -> bool:
    for _attempt in range(6):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:  # noqa: BLE001 - clipboard ocupada por outro processo
            time.sleep(0.05)
    return False


def _win32_get() -> tuple[bool, str]:
    """Devolve ``(ok, texto)`` lendo CF_UNICODETEXT."""
    if not _open_with_retry():
        return False, "área de transferência ocupada por outro programa"
    try:
        try:
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        except Exception:  # noqa: BLE001 - sem dado de texto
            return True, ""
        return True, data if isinstance(data, str) else str(data)
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass


def _win32_set(text: str, clear: bool) -> str | None:
    """Escreve no clipboard; devolve mensagem de erro ou ``None`` se ok."""
    if not _open_with_retry():
        return "área de transferência ocupada por outro programa"
    try:
        if clear:
            win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass
    return None


def _tk_get() -> tuple[bool, str]:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        try:
            value = root.clipboard_get()
        except tk.TclError:
            return True, ""
        return True, value if isinstance(value, str) else str(value)
    finally:
        root.destroy()


def _tk_set(text: str, clear: bool) -> str | None:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        if clear:
            root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
    except tk.TclError as exc:
        return str(exc)
    finally:
        root.destroy()
    return None


@function_tool(SPEC_CLIPBOARD_GET)
@guarded
def pc_clipboard_get(args: dict, ctx: ToolContext) -> ToolResult:
    """Lê o texto do clipboard (pywin32; fallback tkinter)."""
    texto: str | None = None
    erros: list[str] = []
    if win32clipboard is not None:
        sucesso, valor = _win32_get()
        if sucesso:
            texto = valor
        else:
            erros.append(valor)
    if texto is None:
        try:
            sucesso, valor = _tk_get()
            if sucesso:
                texto = valor
            else:
                erros.append(valor)
        except Exception as exc:  # noqa: BLE001 - tkinter pode não existir
            erros.append(f"pywin32/tkinter indisponível: {exc}")
    if texto is None:
        return err("; ".join(erros) or "não consegui ler a área de transferência")
    if len(texto) > _MAX_CLIPBOARD_CHARS:
        texto = texto[:_MAX_CLIPBOARD_CHARS] + "\n[... conteúdo cortado]"
    if not texto:
        return ok_result("área de transferência vazia ou sem texto", data={"chars": 0})
    return ok_result(
        out(ctx, texto, untrusted=True, source="área de transferência"),
        data={"chars": len(texto)},
    )


@function_tool(SPEC_CLIPBOARD_SET)
@guarded
def pc_clipboard_set(args: dict, ctx: ToolContext) -> ToolResult:
    """Escreve texto no clipboard (substitui o conteúdo)."""
    text = args.get("text")
    if not isinstance(text, str):
        return err("text precisa ser uma string")
    if len(text) > _MAX_CLIPBOARD_CHARS:
        return err(f"text grande demais ({len(text)} > {_MAX_CLIPBOARD_CHARS} caracteres)")
    clear = args.get("clear")
    clear = True if clear is None else bool(clear)
    erro: str | None = None
    if win32clipboard is not None:
        erro = _win32_set(text, clear)
    if erro is not None:
        try:
            erro = _tk_set(text, clear)
        except Exception as exc:  # noqa: BLE001
            erro = f"{erro}; tkinter: {exc}"
    if erro is not None:
        return err(f"não consegui escrever na área de transferência: {erro}")
    log.info("pc_clipboard_set: %d caracteres", len(text))
    return ok_result(f"copiado para a área de transferência ({len(text)} caractere(s))",
                     data={"chars": len(text)})
