"""Esquecimento controlado e reforço.

Regras:
- Acesso a uma memória: access_count++, refresh de last_accessed.
- Reforço (confirmação do usuário): reinforcement_count++, importância e
  confiança sobem até um teto.
- Decay: memórias NORMAL não acessadas há tempo perdem importância
  gradualmente (nunca apagadas de uma vez). CRITICAL é imune.
- Expiração: TEMPORARY pode expirar (soft delete). Sempre preservando o
  que é importante.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .db import MemoryDatabase

# Nível que nunca cai por decay para NORMAL.
_FLOOR = {"critical": 9.0, "important": 6.0, "normal": 2.0, "temporary": 0.0}
_DECAY_RATE = 0.9       # multiplicador por passada
_DECAY_AFTER_DAYS = 14  # começa a decair depois de X dias sem uso


def touch(db: MemoryDatabase, memory_id: str) -> None:
    row = db.get_memory(memory_id)
    if not row:
        return
    db.update_memory(memory_id, {
        "access_count": int(row.get("access_count", 0)) + 1,
        "last_accessed": _now(),
    })


def reinforce(db: MemoryDatabase, memory_id: str, by: float = 1.0, up_conf: bool = True) -> None:
    row = db.get_memory(memory_id)
    if not row:
        return
    db.update_memory(memory_id, {
        "reinforcement_count": int(row.get("reinforcement_count", 0)) + 1,
        "importance": min(10.0, float(row.get("importance", 5.0)) + by * 0.5),
        "confidence": min(1.0, float(row.get("confidence", 0.7)) + (0.1 if up_conf else 0.0)),
        "updated_at": _now(),
    })


def apply_decay(db: MemoryDatabase, force: bool = False) -> int:
    """Aplica decay e expira TEMPORARY vencidas. Retorna quantas mudaram."""
    changed = 0
    now = datetime.now(UTC)
    for row in db.query_memories(limit=5000):
        storage = row.get("storage_class", "normal")
        if storage == "critical":
            continue
        last = _parse(row.get("last_accessed"))
        days_idle = (now - last).days if last else 0.0

        if storage == "temporary":
            exp = _parse(row.get("expiration"))
            if exp and now > exp:
                db.soft_delete(row["id"])
                changed += 1
                continue

        if days_idle >= _DECAY_AFTER_DAYS:
            current = float(row.get("importance", 5.0))
            new_val = max(_FLOOR.get(storage, 2.0), current * _DECAY_RATE)
            if new_val != current:
                db.update_memory(row["id"], {"importance": round(new_val, 3)})
                changed += 1
    return changed


def _parse(value: str | None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat()
