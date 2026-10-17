"""Resolução do diretório raiz da memória.

Prefere D:/ARIS_MEMORY (fake configuravel via ARIS_MEMORY_ROOT).
Se a unidade não existir/não for criável, usa um fallback local em
``data/memory_fallback`` para nunca travar a ARIS. O flag
``primary_available`` permite sincronização posterior quando D:
voltar a ficar disponível.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def is_foreign_windows_path(raw: str | os.PathLike[str]) -> bool:
    """True se ``raw`` é um caminho de unidade do Windows (``D:/x``) fora do Windows.

    No Linux/macOS, ``Path("D:/x")`` é um caminho *relativo* válido: o ``mkdir``
    criaria uma pasta literal chamada ``D:`` dentro do diretório atual e a
    memória passaria a depender de onde a ARIS foi iniciada.
    """
    return os.name != "nt" and bool(_WINDOWS_DRIVE_RE.match(str(raw)))


def default_memory_root() -> Path:
    """Raiz padrão da memória: D:/ARIS_MEMORY no Windows, ``<projeto>/data/memory`` no resto."""
    if os.name == "nt":
        return Path("D:/ARIS_MEMORY")
    return _PROJECT_ROOT / "data" / "memory"


def resolve_memory_root(
    primary: Path | None = None,
    fallback: Path | None = None,
) -> tuple[Path, bool]:
    """Retorna (root, primary_available).

    ``primary`` é o caminho preferido (padrão: ``default_memory_root()``).
    Cria o diretório quando possível. Caminhos de unidade do Windows
    (``D:/...``) são ignorados fora do Windows.
    """
    if primary is not None and not is_foreign_windows_path(primary):
        p = primary
    else:
        env = os.getenv("ARIS_MEMORY_ROOT", "")
        p = Path(env) if env and not is_foreign_windows_path(env) else default_memory_root()
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return p, True
    except (OSError, PermissionError):
        pass

    fb = fallback or Path(__file__).resolve().parent.parent.parent / "data" / "memory_fallback"
    try:
        fb.mkdir(parents=True, exist_ok=True)
        return fb, False
    except (OSError, PermissionError):
        return fallback or Path.cwd(), False


def memory_layout(root: Path) -> dict[str, Path]:
    """Estrutura de pastas da memória."""
    names = [
        "database", "episodic", "semantic", "procedural", "conversations",
        "experiences", "files", "embeddings", "indexes", "backups",
        "snapshots", "metadata",
    ]
    layout: dict[str, Path] = {}
    for name in names:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        layout[name] = d
    return layout
