"""Teclado e mouse (pyautogui) — último recurso quando não há UIA."""

from __future__ import annotations

import logging

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import bounded_int, err, guarded, ok_result, out, schema

log = logging.getLogger("aris.agent.tools.pc.input_tools")

try:
    import pyautogui
except Exception as exc:  # noqa: BLE001 - quebra quando não há área gráfica
    pyautogui = None  # type: ignore[assignment]
    _PYAUTOGUI_ERRO = str(exc)
else:
    _PYAUTOGUI_ERRO = ""

_MAX_CHORDS = 8
_MAX_KEYS_PER_CHORD = 6

SPEC_KEYS = ToolSpec(
    name="pc_keys",
    description=(
        "Envia atalho de teclado validado, ex.: ctrl+s, ctrl+shift+s, enter. "
        "Vários atalhos separados por vírgula."
    ),
    parameters=schema(
        {
            "keys": {
                "type": "string",
                "description": "Atalho(s): teclas unidas por + e atalhos por , (ex.: ctrl+s, esc).",
            }
        },
        required=("keys",),
    ),
    risk=Risk.EXEC,
    tags=("pc", "input"),
    timeout_s=10.0,
)

SPEC_MOUSE = ToolSpec(
    name="pc_mouse",
    description=(
        "Move o mouse ou clica em coordenadas (x, y) — último recurso, prefira pc_ui_click. "
        "pyautogui.FAILSAFE fica ligado."
    ),
    parameters=schema(
        {
            "action": {
                "type": "string",
                "enum": ["move", "click", "dblclick", "rightclick", "scroll"],
                "description": "Ação a executar.",
            },
            "x": {"type": "integer", "description": "Coordenada horizontal em pixels."},
            "y": {"type": "integer", "description": "Coordenada vertical em pixels."},
            "dy": {
                "type": "integer",
                "description": "Rodas do scroll (positivo sobe; padrão 3).",
                "minimum": -50,
                "maximum": 50,
            },
        },
        required=("action", "x", "y"),
    ),
    risk=Risk.EXEC,
    tags=("pc", "input"),
    timeout_s=10.0,
)


def _valid_keys() -> set[str]:
    """Teclas que o pyautogui aceita, em minúsculas."""
    if pyautogui is None:
        return set()
    return {str(key).lower() for key in pyautogui.KEYBOARD_KEYS}


@function_tool(SPEC_KEYS)
@guarded
def pc_keys(args: dict, ctx: ToolContext) -> ToolResult:
    """Valida cada tecla contra a lista do pyautogui e envia os atalhos."""
    raw = str(args.get("keys") or "").strip()
    if not raw:
        return err("keys vazio")
    if pyautogui is None:
        return err(f"dependência pyautogui não instalada ou sem área gráfica: {_PYAUTOGUI_ERRO}")

    chords = [part.strip() for part in raw.split(",") if part.strip()]
    if not chords:
        return err(f"keys sem atalho reconhecível: {raw!r}")
    if len(chords) > _MAX_CHORDS:
        return err(f"muitos atalhos de uma vez ({len(chords)} > {_MAX_CHORDS})")

    valid = _valid_keys()
    parsed: list[list[str]] = []
    for chord in chords:
        parts = [part.strip().lower() for part in chord.split("+") if part.strip()]
        if not parts or len(parts) > _MAX_KEYS_PER_CHORD:
            return err(f"atalho inválido: {chord!r} (máx {_MAX_KEYS_PER_CHORD} teclas por atalho)")
        for part in parts:
            if part not in valid:
                return err(
                    f"tecla inválida: {part!r} (use nomes como ctrl, shift, alt, enter, f5, a, 1)"
                )
        parsed.append(parts)

    pyautogui.FAILSAFE = True
    enviados: list[str] = []
    for parts in parsed:
        if len(parts) == 1:
            pyautogui.press(parts[0])
        else:
            pyautogui.hotkey(*parts)
        enviados.append("+".join(parts))
    log.info("pc_keys: %s", enviados)
    return ok_result(out(ctx, f"enviado: {', '.join(enviados)}"), data={"sent": enviados})


@function_tool(SPEC_MOUSE)
@guarded
def pc_mouse(args: dict, ctx: ToolContext) -> ToolResult:
    """Move/clica/rola em coordenadas, validadas contra o tamanho da tela."""
    action = str(args.get("action") or "").strip().lower()
    allowed = {"move", "click", "dblclick", "rightclick", "scroll"}
    if action not in allowed:
        return err(f"action inválida: {action!r} (use uma de {sorted(allowed)})")

    x = bounded_int(args, "x", -1, -10**9, 10**9)
    y = bounded_int(args, "y", -1, -10**9, 10**9)
    if x < 0 or y < 0:
        return err(f"coordenadas inválidas: x={x}, y={y} (devem ser >= 0)")

    if pyautogui is None:
        return err(f"dependência pyautogui não instalada ou sem área gráfica: {_PYAUTOGUI_ERRO}")

    largura, altura = pyautogui.size()
    if x >= largura or y >= altura:
        return err(f"fora da tela: {x},{y} (a tela tem {largura}x{altura})")

    dy = bounded_int(args, "dy", 3, -50, 50)
    pyautogui.FAILSAFE = True
    if action == "move":
        pyautogui.moveTo(x, y, duration=0.05)
    elif action == "click":
        pyautogui.click(x=x, y=y)
    elif action == "dblclick":
        pyautogui.doubleClick(x=x, y=y)
    elif action == "rightclick":
        pyautogui.rightClick(x=x, y=y)
    else:
        pyautogui.moveTo(x, y, duration=0.05)
        pyautogui.scroll(dy)
    log.info("pc_mouse: %s %s,%s", action, x, y)
    return ok_result(
        out(ctx, f"{action} em {x},{y}" + (f" (scroll {dy})" if action == "scroll" else "")),
        data={"action": action, "x": x, "y": y, "dy": dy if action == "scroll" else None},
    )
