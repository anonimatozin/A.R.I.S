"""Abre aplicativos por nome amigável, resolvendo pelo mapa da configuração."""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import err, guarded, ok_result, resolve_path, schema

log = logging.getLogger("aris.agent.tools.pc.apps")

# Chaves da seção "pc" que são opções, não nomes de app.
_OPTION_KEYS = {"apps", "store_fallback", "run_timeout_s", "python_timeout_s", "default_shell"}

# Esquema de URI com 2+ caracteres ("ms-settings:", "https://") — "C:\..." não conta.
_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]{1,}:")

SPEC_OPEN_APP = ToolSpec(
    name="pc_open_app",
    description=(
        "Abre um aplicativo pelo nome cadastrado na seção pc.apps da configuração "
        "(ex.: chrome, calc, notepad). Não recebe caminho livre."
    ),
    parameters=schema(
        {
            "name": {
                "type": "string",
                "description": "Nome amigável do app, como está no mapa de configuração.",
            }
        },
        required=("name",),
    ),
    risk=Risk.EXEC,
    tags=("pc", "apps"),
    timeout_s=20.0,
)


def _app_map(config_section: dict) -> dict[str, str]:
    """Mapa nome->alvo da seção ``pc``: preferindo ``apps``, senão as chaves soltas."""
    apps = config_section.get("apps")
    if isinstance(apps, dict):
        source = apps
    else:
        source = {k: v for k, v in config_section.items() if k not in _OPTION_KEYS}
    return {
        str(key).lower(): str(value).strip()
        for key, value in source.items()
        if isinstance(value, str) and str(value).strip()
    }


def _looks_like_uri(value: str) -> bool:
    """``https://x``, ``ms-settings:display`` sim; ``C:\\x`` não (esquema de 1 letra)."""
    if "://" in value:
        return True
    match = _URI_RE.match(value)
    return bool(match and len(match.group(0)) > 1)


@function_tool(SPEC_OPEN_APP)
@guarded
def pc_open_app(args: dict, ctx: ToolContext) -> ToolResult:
    """Abre o app pelo mapa; se não houver mapa, explica como cadastrar."""
    name = str(args.get("name") or "").strip()
    if not name:
        return err("name vazio")
    if any(sep in name for sep in ("/", "\\")) and not _looks_like_uri(name):
        return err(f"name parece caminho, não nome de app: {name!r} (use o mapa pc.apps)")

    section = ctx.config.section("pc")
    apps = _app_map(section)
    target = apps.get(name.lower())

    if target is None:
        if str(section.get("store_fallback", "")).lower() in {"1", "true", "yes", "on", "sim"}:
            if not hasattr(os, "startfile"):
                return err("abrir a loja precisa de Windows (os.startfile ausente)")
            if any(sep in name for sep in ("/", "\\")):
                return err(f"name inválido para loja: {name!r}")
            target = f"ms-windows-store://search/?query={quote(name)}"
        else:
            return err(
                f"app {name!r} não está cadastrado. Cadastre em aris_agent.json: "
                '"sections": { "pc": { "apps": { "' + name + '": "C:\\\\caminho\\\\app.exe" } } } '
                "(o valor pode ser caminho de exe ou URI como https://...)."
            )

    expanded = os.path.expandvars(target.strip().strip('"'))
    if _looks_like_uri(expanded):
        if not hasattr(os, "startfile"):
            return err("abrir URI precisa de Windows (os.startfile ausente)")
        os.startfile(expanded)
        log.info("pc_open_app: %s -> URI %s", name, expanded)
        return ok_result(f"aberto: {name} -> {expanded}", data={"name": name, "target": expanded})

    path = Path(expanded).expanduser()
    if not path.is_absolute():
        found = shutil.which(expanded)
        if found:
            path = Path(found)
        elif any(sep in expanded for sep in ("/", "\\")):
            path = resolve_path(expanded, ctx, arg=f"apps.{name.lower()}")
        else:
            return err(f"não encontrei {expanded!r} no PATH nem nas raízes permitidas")
    if not path.exists():
        return err(f"caminho cadastrado para {name!r} não existe: {path}")
    if not hasattr(os, "startfile"):
        return err("abrir app precisa de Windows (os.startfile ausente)")
    os.startfile(str(path))
    log.info("pc_open_app: %s -> %s", name, path)
    return ok_result(
        f"aberto: {name} -> {path}", data={"name": name, "target": str(path)}
    )
