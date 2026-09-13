"""Sistema de associação entre memórias e detecção de contradição."""

from __future__ import annotations

from .db import MemoryDatabase
from .texting import extract_entities, is_contradiction


def associate(db: MemoryDatabase, memory_id: str, other_id: str,
              relationship: str, strength: float = 0.8, notes: str = "") -> None:
    """Cria uma relação entre duas memórias (idempotente por par)."""
    existing = db.list_associations(memory_id)
    if any(a["other"] == other_id and a["relationship_type"] == relationship for a in existing):
        return
    db.add_association(memory_id, other_id, relationship, strength, notes)


def related_memories(db: MemoryDatabase, memory_id: str, depth: int = 2) -> list[str]:
    """Percorre as associações até ``depth`` níveis."""
    visited: set[str] = set()
    frontier = [memory_id]
    for _ in range(depth):
        nxt: list[str] = []
        for mid in frontier:
            if mid in visited:
                continue
            visited.add(mid)
            for assoc in db.list_associations(mid):
                other = assoc["other"]
                if other not in visited:
                    nxt.append(other)
        frontier = nxt
    visited.discard(memory_id)
    return list(visited)


def detect_contradiction(db: MemoryDatabase, new_content: str,
                         new_type: str) -> list[str]:
    """Retorna ids de memórias existentes que a nova informação pode contradizer."""
    if not is_contradiction(new_content) or new_type not in ("semantic", "conversation"):
        return []
    new_ent = set(extract_entities(new_content, limit=12))
    candidates = []
    for row in db.query_memories(memory_type="semantic", limit=500):
        ent = set(_load_list(row.get("entities")))
        if new_ent and len(ent & new_ent) >= 1:
            candidates.append(row["id"])
    return candidates


def _load_list(value) -> list[str]:
    import json
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []
