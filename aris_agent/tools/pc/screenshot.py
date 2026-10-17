"""Captura de tela para PNG no workspace (o LLM recebe só o caminho, não a imagem)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import err, guarded, ok_result, out, resolve_path, schema

log = logging.getLogger("aris.agent.tools.pc.screenshot")

try:
    import pyautogui
except Exception as exc:  # noqa: BLE001 - quebra quando não há área gráfica
    pyautogui = None  # type: ignore[assignment]
    _PYAUTOGUI_ERRO = str(exc)
else:
    _PYAUTOGUI_ERRO = ""

SPEC_SCREENSHOT = ToolSpec(
    name="pc_screenshot",
    description="Tira uma captura de tela, salva no workspace e devolve o caminho do PNG.",
    parameters=schema(
        {
            "filename": {
                "type": "string",
                "description": "Nome/caminho opcional do PNG (dentro das raízes permitidas).",
            }
        }
    ),
    risk=Risk.READ,
    tags=("pc", "screenshot"),
    path_args=("filename",),
    timeout_s=30.0,
)


@function_tool(SPEC_SCREENSHOT)
@guarded
def pc_screenshot(args: dict, ctx: ToolContext) -> ToolResult:
    """Salva a tela em PNG e devolve o caminho (sem descrever a imagem)."""
    if pyautogui is None:
        return err(f"dependência pyautogui não instalada ou sem área gráfica: {_PYAUTOGUI_ERRO}")
    pyautogui.FAILSAFE = True

    raw = args.get("filename")
    if raw:
        dest = resolve_path(raw, ctx, arg="filename")
        if dest.suffix.lower() != ".png":
            dest = dest.with_suffix(".png")
    else:
        workspace = Path(ctx.config.workspace_dir).expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        dest = workspace / f"screenshot_{time.strftime('%Y%m%d-%H%M%S')}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    image = pyautogui.screenshot()
    image.save(str(dest), format="PNG")
    size = dest.stat().st_size
    log.info("pc_screenshot: %s (%d bytes)", dest, size)
    return ok_result(
        out(ctx, f"captura salva em {dest}"),
        data={"path": str(dest), "bytes": size},
        artifacts=[str(dest)],
    )
