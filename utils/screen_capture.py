"""Captura de tela no Linux com a ferramenta certa por sessão (Fase 6).

No Linux, ``pyautogui.screenshot`` depende de X11 e falha em Wayland
(gerando arquivo vazio/inválido — "cannot identify image file"). Este
módulo detecta ``XDG_SESSION_TYPE`` e usa a ferramenta adequada:

- Wayland  → grim
- X11      → scrot  (fallback: gnome-screenshot, import)

Valida o arquivo gerado (existe + é imagem legível) antes de devolver.
Se nenhuma ferramenta existir, devolve erro claro.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def session_type() -> str:
    """Retorna 'wayland', 'x11' ou 'unknown'."""
    xdg = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if xdg in ("wayland", "x11"):
        return xdg
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def _candidate_tools() -> list[list[str]]:
    """Ferramentas candidatas na ordem certa para a sessão atual."""
    stype = session_type()
    tools: list[list[str]] = []
    if stype == "wayland":
        tools.append(["grim", "{out}"])
        tools.append(["gnome-screenshot", "-f", "{out}"])
        tools.append(["scrot", "-o", "{out}"])  # scrot pode funcionar via XWayland
    elif stype == "x11":
        tools.append(["scrot", "-o", "{out}"])
        tools.append(["gnome-screenshot", "-f", "{out}"])
        tools.append(["import", "-window", "root", "{out}"])
    else:
        # Sessão desconhecida: tenta tudo, na ordem de preferência.
        tools.append(["grim", "{out}"])
        tools.append(["scrot", "-o", "{out}"])
        tools.append(["gnome-screenshot", "-f", "{out}"])
        tools.append(["import", "-window", "root", "{out}"])
    return tools


def capture_to(path: str | Path, timeout: int = 20) -> tuple[bool, str]:
    """Captura a tela para ``path``.

    Returns:
        (ok, mensagem). Em ``ok=True``, ``path`` contém uma imagem válida.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tried: list[str] = []
    for argv_template in _candidate_tools():
        exe = argv_template[0]
        if not shutil.which(exe):
            continue
        argv = [a.format(out=str(path)) for a in argv_template]
        tried.append(exe)
        try:
            subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        except Exception:
            continue
        if _is_valid_image(path):
            return True, str(path)

    if not tried:
        return False, (
            "Nenhuma ferramenta de captura de tela disponível no Linux "
            "(instale grim no Wayland, ou scrot/gnome-screenshot no X11)."
        )
    return False, (
        f"Ferramentas tentadas ({', '.join(tried)}) não produziram uma imagem "
        f"válida (sessão: {session_type()})."
    )


def _is_valid_image(path: Path) -> bool:
    """Arquivo existe, não está vazio e é uma imagem legível pelo PIL."""
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return False
    except OSError:
        return False
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def available_tool() -> str | None:
    """Nome da primeira ferramenta de captura disponível (para diagnóstico)."""
    for argv_template in _candidate_tools():
        if shutil.which(argv_template[0]):
            return argv_template[0]
    return None
