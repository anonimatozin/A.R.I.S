"""Resolução do diretório raiz da memória.

Prefere D:/ARIS_MEMORY (fake configuravel via ARIS_MEMORY_ROOT).
Se a unidade não existir/não for criável, usa um fallback local em
``data/memory_fallback`` para nunca travar a ARIS. O flag
``primary_available`` permite sincronização posterior quando D:
voltar a ficar disponível.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_memory_root(
    primary: Path | None = None,
    fallback: Path | None = None,
) -> tuple[Path, bool]:
    """Retorna (root, primary_available).

    ``primary`` é o caminho preferido (padrão D:/ARIS_MEMORY).
    Cria o diretório quando possível.
    """
    p = primary or Path(os.getenv("ARIS_MEMORY_ROOT", "D:/ARIS_MEMORY"))
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
