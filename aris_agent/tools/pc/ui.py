"""UI Automation com pywinauto (backend ``uia``): listar, clicar e digitar em controles."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import bounded_int, err, guarded, ok_result, out, schema

log = logging.getLogger("aris.agent.tools.pc.ui")

try:
    from pywinauto import Desktop
    from pywinauto.uia_defines import NoPatternInterfaceError
except Exception as exc:  # noqa: BLE001 - falha quando não há UIA/desktop
    Desktop = None  # type: ignore[assignment]
    NoPatternInterfaceError = Exception  # type: ignore[assignment]
    _UIA_ERRO = str(exc)
else:
    _UIA_ERRO = ""

SPEC_UI_FIND = ToolSpec(
    name="pc_ui_find",
    description=(
        "Lista os controles de uma janela via UI Automation (nome, tipo, id) "
        "em árvore resumida. Use antes de pc_ui_click/pc_ui_type."
    ),
    parameters=schema(
        {
            "window_title": {"type": "string", "description": "Parte do título da janela (sem maiúsculas)."},
            "max_depth": {
                "type": "integer",
                "description": "Profundidade da árvore (padrão 4, até 10).",
                "minimum": 1,
                "maximum": 10,
            },
            "max_items": {
                "type": "integer",
                "description": "Máximo de controles listados (padrão 200, até 1000).",
                "minimum": 1,
                "maximum": 1000,
            },
        },
        required=("window_title",),
    ),
    risk=Risk.READ,
    untrusted_output=True,
    tags=("pc", "ui"),
    timeout_s=30.0,
)

SPEC_UI_CLICK = ToolSpec(
    name="pc_ui_click",
    description="Invoca/clica um controle encontrado por nome/tipo/id dentro de uma janela (UIA).",
    parameters=schema(
        {
            "window_title": {"type": "string", "description": "Parte do título da janela (sem maiúsculas)."},
            "control_name": {"type": "string", "description": "Nome do controle (subcadena, sem maiúsculas)."},
            "control_type": {"type": "string", "description": "Tipo UIA, ex.: Button, Edit, MenuItem."},
            "control_id": {"type": "string", "description": "AutomationId exato do controle."},
            "index": {
                "type": "integer",
                "description": "Qual controle usar se vários casarem (padrão 0).",
                "minimum": 0,
            },
        },
        required=("window_title",),
    ),
    risk=Risk.EXEC,
    tags=("pc", "ui"),
    timeout_s=20.0,
)

SPEC_UI_TYPE = ToolSpec(
    name="pc_ui_type",
    description=(
        "Digita texto num controle (UIA) ou na janela ativa; prefere ValuePattern "
        "e usa teclas Unicode como alternativa."
    ),
    parameters=schema(
        {
            "window_title": {"type": "string", "description": "Parte do título da janela (sem maiúsculas)."},
            "text": {"type": "string", "description": "Texto a digitar (aceita acentos e quebras de linha)."},
            "control_name": {"type": "string", "description": "Nome do controle (subcadena, sem maiúsculas)."},
            "control_type": {"type": "string", "description": "Tipo UIA, ex.: Edit, ComboBox."},
            "control_id": {"type": "string", "description": "AutomationId exato do controle."},
            "index": {
                "type": "integer",
                "description": "Qual controle usar se vários casarem (padrão 0).",
                "minimum": 0,
            },
        },
        required=("window_title", "text"),
    ),
    risk=Risk.EXEC,
    tags=("pc", "ui"),
    timeout_s=20.0,
)


def _require_uia() -> str | None:
    if Desktop is None:
        return f"dependência pywinauto/UIA indisponível: {_UIA_ERRO}"
    return None


def _find_window(title: str):
    """Primeira janela top-level visível cujo título contém ``title`` (sem maiúsculas)."""
    wanted = title.lower()
    for window in Desktop(backend="uia").windows():
        try:
            text = (window.window_text() or "").lower()
            if wanted in text and window.is_visible():
                return window
        except Exception:  # noqa: BLE001 - janela pode sumir no meio da enumeração
            continue
    return None


def _window_titles(limit: int = 10) -> list[str]:
    titles: list[str] = []
    for window in Desktop(backend="uia").windows():
        try:
            text = window.window_text() or ""
        except Exception:  # noqa: BLE001
            continue
        if text and text not in titles:
            titles.append(text)
        if len(titles) >= limit:
            break
    return titles


def _match_controls(window, args: dict) -> list:
    """Controles da janela que casam com os filtros fornecidos (E lógico)."""
    name = str(args.get("control_name") or "").strip().lower()
    control_type = str(args.get("control_type") or "").strip().lower()
    control_id = str(args.get("control_id") or "").strip()
    matches: list = []
    for ctrl in window.descendants():
        try:
            info = ctrl.element_info
            if name and name not in (info.name or "").lower():
                continue
            if control_type and (info.control_type or "").lower() != control_type:
                continue
            if control_id and (info.automation_id or "") != control_id:
                continue
        except Exception:  # noqa: BLE001
            continue
        matches.append(ctrl)
    return matches


@function_tool(SPEC_UI_FIND)
@guarded
def pc_ui_find(args: dict, ctx: ToolContext) -> ToolResult:
    """Lista controles da janela como árvore resumida (nome, tipo, AutomationId)."""
    missing = _require_uia()
    if missing:
        return err(missing)
    title = str(args.get("window_title") or "").strip()
    if not title:
        return err("window_title vazio")
    max_depth = bounded_int(args, "max_depth", 4, 1, 10)
    max_items = bounded_int(args, "max_items", 200, 1, 1000)

    window = _find_window(title)
    if window is None:
        return err(
            f"nenhuma janela com título contendo {title!r}. "
            f"Janelas abertas: {', '.join(_window_titles()) or '(nenhuma)'}"
        )

    records: list[dict] = []
    try:
        _collect(window.element_info, 1, max_depth, records, max_items, ctx)
    except Exception as exc:  # noqa: BLE001 - UIA pode falhar no meio
        return err(f"UIA falhou ao percorrer a janela: {exc}")
    if not records:
        return ok_result(
            out(ctx, f"Janela {window.window_text()!r} sem controles filhos visíveis."),
            data={"controls": []},
        )

    lines = [f"Janela: {window.window_text()!r}"]
    for index, record in enumerate(records):
        indent = "  " * record["depth"]
        name = record["name"] or "(sem nome)"
        lines.append(
            f"{indent}[{index}] {record['type'] or '?'} nome={name!r} id={record['id'] or ''}"
        )
    if len(records) >= max_items:
        lines.append(f"[... limite de {max_items} controles atingido; use max_items maior]")
    return ok_result(
        out(ctx, "\n".join(lines), untrusted=True, source="controles da janela"),
        data={"controls": records, "window": window.window_text()},
    )


def _collect(element_info, depth: int, max_depth: int, records: list, limit: int, ctx) -> None:
    """Percorre os filhos até ``max_depth``/``limit``, respeitando ``ctx.cancel``."""
    if depth > max_depth or len(records) >= limit:
        return
    try:
        children = element_info.children()
    except Exception:  # noqa: BLE001 - elemento pode ficar indisponível
        return
    for child in children:
        if len(records) >= limit or ctx.cancel.is_set():
            return
        try:
            record = {
                "name": child.name or "",
                "type": child.control_type or "",
                "id": child.automation_id or "",
                "class": child.class_name or "",
                "depth": depth,
            }
        except Exception:  # noqa: BLE001
            continue
        records.append(record)
        _collect(child, depth + 1, max_depth, records, limit, ctx)


@function_tool(SPEC_UI_CLICK)
@guarded
def pc_ui_click(args: dict, ctx: ToolContext) -> ToolResult:
    """Invoca o controle (padrão Invoke) ou clica nele como alternativa."""
    missing = _require_uia()
    if missing:
        return err(missing)
    title = str(args.get("window_title") or "").strip()
    if not title:
        return err("window_title vazio")
    if not any(args.get(key) for key in ("control_name", "control_type", "control_id")):
        return err("informe control_name, control_type ou control_id (veja pc_ui_find)")

    window = _find_window(title)
    if window is None:
        return err(f"nenhuma janela com título contendo {title!r}")
    matches = _match_controls(window, args)
    if not matches:
        return err(f"nenhum controle em {title!r} com os filtros dados (use pc_ui_find)")
    index = bounded_int(args, "index", 0, 0, len(matches) - 1)
    ctrl = matches[index]
    acao = "invoke"
    try:
        ctrl.invoke()
    except NoPatternInterfaceError:
        acao = "click"
        try:
            ctrl.click_input()
        except Exception as exc:  # noqa: BLE001
            return err(f"controle não aceitou clique: {exc}")
    except Exception as exc:  # noqa: BLE001 - Invoke pode falhar por estado
        log.debug("invoke falhou (%s); tentando clique", exc)
        acao = "click"
        try:
            ctrl.click_input()
        except Exception as exc2:  # noqa: BLE001
            return err(f"não consegui acionar o controle: {exc2}")
    info = ctrl.element_info
    log.info("pc_ui_click: %s %r em %r", acao, info.name, title)
    return ok_result(
        f"{acao} em controle {index + 1}/{len(matches)}: "
        f"{info.control_type or '?'} nome={info.name!r}",
        data={"action": acao, "matches": len(matches), "index": index},
    )


@function_tool(SPEC_UI_TYPE)
@guarded
def pc_ui_type(args: dict, ctx: ToolContext) -> ToolResult:
    """Digita texto: ValuePattern quando existe, senão teclas Unicode com foco."""
    missing = _require_uia()
    if missing:
        return err(missing)
    title = str(args.get("window_title") or "").strip()
    if not title:
        return err("window_title vazio")
    text = args.get("text")
    if not isinstance(text, str):
        return err("text precisa ser uma string")

    window = _find_window(title)
    if window is None:
        return err(f"nenhuma janela com título contendo {title!r}")

    has_filter = any(args.get(key) for key in ("control_name", "control_type", "control_id"))
    ctrl = None
    if has_filter:
        matches = _match_controls(window, args)
        if not matches:
            return err(f"nenhum controle em {title!r} com os filtros dados (use pc_ui_find)")
        index = bounded_int(args, "index", 0, 0, len(matches) - 1)
        ctrl = matches[index]

    if ctrl is not None:
        try:
            ctrl.iface_value.SetValue(text)
            info = ctrl.element_info
            log.info("pc_ui_type: ValuePattern em %r", info.name)
            return ok_result(
                f"texto definido via ValuePattern em {info.control_type or '?'} "
                f"nome={info.name!r} ({len(text)} caractere(s))",
                data={"method": "value", "chars": len(text)},
            )
        except NoPatternInterfaceError:
            pass
        except Exception as exc:  # noqa: BLE001 - app pode recusar o ValuePattern
            log.debug("SetValue falhou (%s); usando teclas", exc)

    try:
        target = ctrl if ctrl is not None else window
        target.set_focus()
    except Exception as exc:  # noqa: BLE001
        return err(f"não consegui focar o controle/janela: {exc}")
    sent, esperado = _send_unicode(text)
    if sent != esperado:
        return err(f"enviei {sent} de {esperado} eventos de tecla (Windows pode ter bloqueado)")
    log.info("pc_ui_type: %d caracteres via SendInput em %r", len(text), title)
    return ok_result(
        f"digitado {len(text)} caractere(s) em {title!r}"
        + ("" if ctrl is None else f" (controle {ctrl.element_info.control_type or '?'})"),
        data={"method": "keys", "chars": len(text)},
    )


_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004


def _send_unicode(text: str) -> tuple[int, int]:
    """Digita texto Unicode via SendInput (KEYEVENTF_UNICODE).

    Devolve ``(eventos_enviados, eventos_esperados)`` — 2 eventos por unidade UTF-16.
    """
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    data = normalized.encode("utf-16-le")
    units = [data[i] | (data[i + 1] << 8) for i in range(0, len(data), 2)]
    events: list[INPUT] = []
    for unit in units:
        if unit == 0x0A:  # quebra de linha vira Enter de verdade (VK_RETURN)
            for flags in (0, _KEYEVENTF_KEYUP):
                events.append(INPUT(type=_INPUT_KEYBOARD, ki=KEYBDINPUT(0x0D, 0, flags, 0, 0)))
            continue
        for flags in (_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP):
            events.append(INPUT(type=_INPUT_KEYBOARD, ki=KEYBDINPUT(0, unit, flags, 0, 0)))
    esperado = len(events)
    if not events:
        return 0, 0
    array = (INPUT * len(events))(*events)
    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    sent = user32.SendInput(
        len(events), ctypes.cast(array, ctypes.POINTER(INPUT)), ctypes.sizeof(INPUT)
    )
    return int(sent), esperado
