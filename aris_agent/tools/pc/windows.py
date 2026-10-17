"""Janelas abertas e foco de janela (win32gui / pywin32)."""

from __future__ import annotations

import logging

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import bounded_int, err, guarded, ok_result, out, schema

log = logging.getLogger("aris.agent.tools.pc.windows")

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:  # pragma: no cover - só existe no Windows
    win32api = None  # type: ignore[assignment]
    win32con = None  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]
    win32process = None  # type: ignore[assignment]

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

SPEC_LIST_WINDOWS = ToolSpec(
    name="pc_list_windows",
    description="Lista janelas abertas (título, processo, pid, qual está ativa).",
    parameters=schema(
        {
            "title": {"type": "string", "description": "Filtra por parte do título (sem maiúsculas)."},
            "limit": {
                "type": "integer",
                "description": "Máximo de janelas (padrão 100, até 500).",
                "minimum": 1,
                "maximum": 500,
            },
        }
    ),
    risk=Risk.READ,
    tags=("pc", "windows"),
    timeout_s=10.0,
)

SPEC_FOCUS_WINDOW = ToolSpec(
    name="pc_focus_window",
    description="Traz uma janela para frente (foco), restaurando se estiver minimizada.",
    parameters=schema(
        {"title": {"type": "string", "description": "Parte do título da janela (sem maiúsculas)."}},
        required=("title",),
    ),
    risk=Risk.EXEC,
    tags=("pc", "windows"),
    timeout_s=10.0,
)


def _require_win32() -> str | None:
    """Mensagem de dependência ausente, ou ``None`` se tudo ok."""
    if win32gui is None or win32process is None:
        return "dependência pywin32 não instalada (requirements/parte2.txt)"
    return None


def _process_name(pid: int) -> str:
    if psutil is None:
        return "?"
    try:
        return psutil.Process(pid).name()
    except Exception:  # noqa: BLE001 - processo pode ter saído
        return "?"


def _collect_windows(title_filter: str = "") -> list[dict]:
    """Enumera janelas top-level visíveis com título."""
    found: list[dict] = []
    foreground = win32gui.GetForegroundWindow()
    wanted = title_filter.lower()

    def _callback(hwnd: int, accumulator: list[dict]) -> None:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd) or ""
        except Exception:  # noqa: BLE001
            return
        if not title or (wanted and wanted not in title.lower()):
            return
        try:
            _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:  # noqa: BLE001
            pid = 0
        accumulator.append(
            {
                "hwnd": hwnd,
                "title": title,
                "pid": pid,
                "process": _process_name(pid),
                "active": hwnd == foreground,
            }
        )

    win32gui.EnumWindows(_callback, found)
    found.sort(key=lambda item: (not item["active"], item["title"].lower()))
    return found


@function_tool(SPEC_LIST_WINDOWS)
@guarded
def pc_list_windows(args: dict, ctx: ToolContext) -> ToolResult:
    """Lista janelas visíveis com título, processo e qual está ativa."""
    missing = _require_win32()
    if missing:
        return err(missing)
    title_filter = str(args.get("title") or "").strip()
    limit = bounded_int(args, "limit", 100, 1, 500)
    windows = _collect_windows(title_filter)
    selected = windows[:limit]
    if not selected:
        return ok_result(
            out(ctx, f"Nenhuma janela aberta com título contendo {title_filter!r}."),
            data={"windows": [], "total": 0},
        )
    lines = []
    for window in selected:
        mark = " [ativa]" if window["active"] else ""
        lines.append(
            f"hwnd={window['hwnd']}{mark}  {window['title']!r} — "
            f"{window['process']} (pid {window['pid']})"
        )
    header = f"{len(selected)} de {len(windows)} janela(s)"
    return ok_result(
        out(ctx, f"{header}\n" + "\n".join(lines), untrusted=True, source="lista de janelas"),
        data={"windows": selected, "total": len(windows)},
    )


@function_tool(SPEC_FOCUS_WINDOW)
@guarded
def pc_focus_window(args: dict, ctx: ToolContext) -> ToolResult:
    """Restaura e traz para frente a primeira janela cujo título casa com o filtro."""
    missing = _require_win32()
    if missing:
        return err(missing)
    title = str(args.get("title") or "").strip()
    if not title:
        return err("title vazio")
    matches = _collect_windows(title)
    if not matches:
        return err(f"nenhuma janela visível com título contendo {title!r}")
    window = matches[0]
    hwnd = window["hwnd"]
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:  # noqa: BLE001 - Windows pode negar o foreground
        log.debug("SetForegroundWindow direto falhou (%s); tentando truque do ALT", exc)
        try:
            win32api.keybd_event(0x12, 0, 0, 0)  # ALT para baixo
            win32api.keybd_event(0x12, 0, win32con.KEYEVENTF_KEYUP, 0)  # ALT para cima
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc2:  # noqa: BLE001
            return err(f"Windows bloqueou o foco da janela {window['title']!r}: {exc2}")
    active = win32gui.GetForegroundWindow() == hwnd
    if not active:
        win32gui.BringWindowToTop(hwnd)
        active = win32gui.GetForegroundWindow() == hwnd
    if not active:
        return err(
            f"não consegui colocar {window['title']!r} em primeiro plano "
            "(Windows restringe SetForegroundWindow)"
        )
    extra = f" (outras {len(matches) - 1} janela(s) com o mesmo título ignoradas)" if len(matches) > 1 else ""
    return ok_result(
        f"foco em: {window['title']!r} — {window['process']} (pid {window['pid']}){extra}",
        data=window,
    )
