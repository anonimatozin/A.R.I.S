"""Recuperação de memória relevante (Memory Retriever).

Busca combinando similaridade textual, tags, entidades, tipo, importância,
recência, frequência de acesso e confiança. Não despeja o banco inteiro
no LLM: retorna apenas as melhores memórias.
"""

from __future__ import annotations

from datetime import UTC

from .db import MemoryDatabase
from .texting import extract_entities, similarity

# Pesos do escore de relevância.
_W_SIM = 1.0
_W_ENTITY = 0.8
_W_TAG = 0.4
_W_IMPORTANCE = 0.12
_W_CONFIG = 0.05   # confiança
_W_ACCESS = 0.01
_W_RECENCY_HOURS = 0.002


def _recency_bonus(created_at: str, now_hours: float = 0.0) -> float:
    try:
        from datetime import datetime
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age_h = (datetime.now(UTC) - created).total_seconds() / 3600.0
    except Exception:
        age_h = 24.0
    return max(0.0, _W_RECENCY_HOURS * max(0.0, 24.0 - age_h))


def retrieve(
    db: MemoryDatabase,
    query: str,
    context: dict | None = None,
    limit: int = 10,
    memory_type: str | None = None,
) -> list[dict]:
    """Retorna até ``limit`` memórias ordenadas por relevância."""
    q_entities = set(extract_entities(query, limit=20))
    results = []

    for row in db.query_memories(memory_type=memory_type, limit=2000):
        if row.get("deleted"):
            continue
        content = row.get("content", "") or ""
        tags = _load_list(row.get("tags"))
        entities = _load_list(row.get("entities"))

        score = 0.0
        score += _W_SIM * similarity(query, content)
        ent_hit = len(q_entities & set(entities))
        score += _W_ENTITY * min(1.0, ent_hit / 3.0)
        tag_hit = len(q_entities & set(tags))
        score += _W_TAG * min(1.0, tag_hit / 2.0)
        score += _W_IMPORTANCE * (float(row.get("importance", 5.0)) / 10.0)
        score += _W_CONFIG * float(row.get("confidence", 0.7))
        score += _W_ACCESS * (float(row.get("access_count", 0)) / 20.0)
        score += _recency_bonus(str(row.get("created_at", "")), 0.0)

        if score > 0.0:
            row["_score"] = round(score, 4)
            results.append(row)

    if context:
        for key, value in context.items():
            if not isinstance(value, str):
                continue
            ent = extract_entities(value, limit=5)
            for row in results:
                row["_score"] = row.get("_score", 0.0) + (
                    _W_ENTITY * len(set(ent) & set(_load_list(row.get("entities")))) / 10.0
                )

    results.sort(key=lambda r: r.get("_score", 0.0), reverse=True)
    top = results[:limit]
    for row in top:
        _bump_access(db, row["id"])
    return top


def _bump_access(db: MemoryDatabase, memory_id: str) -> None:
    from datetime import datetime
    row = db.get_memory(memory_id)
    if not row:
        return
    db.update_memory(memory_id, {
        "access_count": int(row.get("access_count", 0)) + 1,
        "last_accessed": datetime.now().astimezone().isoformat(),
    })


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
