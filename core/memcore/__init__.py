"""Memória cognitiva do A.R.I.S. (subsistema core/memcore).

Arquitetura inspirada na memória humana, mas computacional:
camadas (trabalho, episódica, semântica, procedural, conversação),
consolidação, decaimento, associações, recuperação, backup e
migração. Armazenamento principal: SQLite (padrão D:/ARIS_MEMORY)
com fallback local quando a unidade não existe.
"""

from .models import Association, MemoryItem, MemoryKind, StorageClass
from .service import MemoryService

__all__ = [
    "MemoryService",
    "MemoryItem",
    "Association",
    "MemoryKind",
    "StorageClass",
]
