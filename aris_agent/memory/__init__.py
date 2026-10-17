"""Memória de longo prazo da A.R.I.S. (Parte 4).

Uso básico::

    from aris_agent.memory import SqliteMemory

    mem = SqliteMemory("data/memory.sqlite3")   # ou open_memory(cfg)
    mem.remember("Vinicius prefere café sem açúcar", kind="preference")
    itens = mem.recall("o que ele gosta de beber?")
"""

from __future__ import annotations

from .embedder import Embedder
from .schema import SCHEMA_VERSION
from .sqlite import (
    VALID_KINDS,
    VALID_ROLES,
    WIPE_CONFIRM_TOKEN,
    SqliteMemory,
    open_memory,
)

__all__ = [
    "SCHEMA_VERSION",
    "VALID_KINDS",
    "VALID_ROLES",
    "WIPE_CONFIRM_TOKEN",
    "Embedder",
    "SqliteMemory",
    "open_memory",
]
