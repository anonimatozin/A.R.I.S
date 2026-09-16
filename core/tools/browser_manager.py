"""Universal Browser Manager — detecta e abre navegadores automaticamente.

Detecta navegadores instalados no Windows dinamicamente.
Nao depende de caminhos fixos.
"""
from __future__ import annotations

import os
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Browser:
    name: str
    path: str
    is_default: bool = False

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.path)


_SEARCH_DIRS = [
    os.environ.get("PROGRAMFILES", r"C:\Program Files"),
    os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
    os.environ.get("LOCALAPPDATA", ""),
]

_KNOWN_BROWSERS = [
    ("edge", "Microsoft/Edge/Application/msedge.exe"),
    ("chrome", "Google/Chrome/Application/chrome.exe"),
    ("firefox", "Mozilla Firefox/firefox.exe"),
    ("opera", "Opera/opera.exe"),
    ("brave", "BraveSoftware/Brave-Browser/Application/brave.exe"),
    ("vivaldi", "Vivaldi/Application/vivaldi.exe"),
]


def _get_default_browser() -> str | None:
    """Detecta navegador padrao do Windows via registro."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        )
        prog_id, _ = winreg.QueryValueEx(key, "ProgID")
        winreg.CloseKey(key)

        cmd_key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command")
        cmd, _ = winreg.QueryValueEx(cmd_key, "")
        winreg.CloseKey(cmd_key)

        if cmd.startswith('"'):
            return cmd.split('"')[1]
        return cmd.split()[0]
    except Exception:
        return None


def detect_browsers() -> list[Browser]:
    """Detecta todos os navegadores instalados no Windows."""
    browsers = []
    default_path = _get_default_browser()
    found_paths = set()

    for name, rel_path in _KNOWN_BROWSERS:
        for search_dir in _SEARCH_DIRS:
            if not search_dir:
                continue
            full = os.path.join(search_dir, rel_path)
            if os.path.isfile(full) and full not in found_paths:
                is_def = default_path and os.path.normpath(full) == os.path.normpath(default_path)
                browsers.append(Browser(name=name, path=full, is_default=is_def))
                found_paths.add(full)

    if default_path and default_path not in found_paths:
        browsers.insert(0, Browser(name="default", path=default_path, is_default=True))

    return browsers


def open_browser(url: str | None = None, browser_name: str = "auto") -> dict:
    """Abre navegador com URL.

    Args:
        url: URL para abrir. Se None, abre pagina em branco.
        browser_name: "auto" detecta padrao, ou nome especifico.

    Returns:
        dict com resultado da operacao.
    """
    browsers = detect_browsers()
    if not browsers:
        return {"ok": False, "error": "Nenhum navegador encontrado no sistema."}

    target = None
    if browser_name != "auto":
        for b in browsers:
            if b.name == browser_name:
                target = b
                break

    if target is None:
        for b in browsers:
            if b.is_default:
                target = b
                break

    if target is None:
        target = browsers[0]

    if not target.exists:
        return {"ok": False, "error": f"Navegador '{target.name}' encontrado mas executavel nao existe: {target.path}"}

    try:
        args = [target.path]
        if url:
            args.append(url)
        subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.SW_SHOW)
        return {"ok": True, "browser": target.name, "url": url or "home"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def search_web(query: str, browser_name: str = "auto") -> dict:
    """Pesquisa na web usando navegador detectado."""
    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    return open_browser(search_url, browser_name)


def get_browser_info() -> dict:
    """Retorna informacoes sobre navegadores detectados."""
    browsers = detect_browsers()
    return {
        "count": len(browsers),
        "browsers": [
            {"name": b.name, "path": b.path, "default": b.is_default, "exists": b.exists}
            for b in browsers
        ],
    }
