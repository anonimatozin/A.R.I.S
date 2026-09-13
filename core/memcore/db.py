"""Camada de banco SQLite da memória cognitiva.

Banco único (``aris_memory.db``), sem tabela por tipo. Inclui
verificação de integridade e recuperação a partir de backup quando
o arquivo está corrompido (o original é sempre preservado).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    storage_class TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_accessed TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 5.0,
    confidence REAL NOT NULL DEFAULT 0.7,
    source TEXT,
    tags TEXT,
    entities TEXT,
    access_count INTEGER NOT NULL DEFAULT 0,
    reinforcement_count INTEGER NOT NULL DEFAULT 0,
    expiration TEXT,
    metadata TEXT,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_class ON memories(storage_class);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);

CREATE TABLE IF NOT EXISTS associations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    related_memory_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    strength REAL NOT NULL DEFAULT 0.8,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_assoc_from ON associations(memory_id);
CREATE INDEX IF NOT EXISTS idx_assoc_to ON associations(related_memory_id);

CREATE TABLE IF NOT EXISTS working_memory (
    slot TEXT PRIMARY KEY,
    goal TEXT,
    entities TEXT,
    constraints TEXT,
    status TEXT,
    steps TEXT,
    results TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_text TEXT NOT NULL,
    ai_text TEXT DEFAULT '',
    importance REAL NOT NULL DEFAULT 3.0,
    entities TEXT,
    created_at TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0
);
"""


class MemoryDatabase:
    """Gerencia a conexão SQLite e a execução de statements."""

    def __init__(self, db_path: Path, backups_dir: Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backups_dir = backups_dir or (self.db_path.parent.parent / "backups")
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.DatabaseError:
            pass
        try:
            self.ensure_schema()
        except sqlite3.DatabaseError:
            # arquivo corrompido: recuperação acontece no boot()
            pass

    # ── infra ──────────────────────────────────────────────

    def ensure_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self.set_meta("schema_version", str(SCHEMA_VERSION))
        self._conn.commit()

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def integrity_ok(self) -> bool:
        try:
            rows = self._conn.execute("PRAGMA integrity_check").fetchall()
            return bool(rows) and rows[0][0] == "ok"
        except sqlite3.DatabaseError:
            return False

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ── memories ───────────────────────────────────────────

    def insert_memory(self, row: tuple) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO memories
               (id, memory_type, storage_class, content, summary,
                created_at, updated_at, last_accessed, importance,
                confidence, source, tags, entities, access_count,
                reinforcement_count, expiration, metadata, deleted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'{}',0)""",
            row,
        )
        self._conn.commit()

    def get_memory(self, memory_id: str) -> dict | None:
        r = self._conn.execute(
            "SELECT * FROM memories WHERE id=? AND deleted=0", (memory_id,)
        ).fetchone()
        return dict(r) if r else None

    def update_memory(self, memory_id: str, fields: dict) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self._conn.execute(
            f"UPDATE memories SET {sets} WHERE id=?",
            (*fields.values(), memory_id),
        )
        self._conn.commit()

    def soft_delete(self, memory_id: str) -> None:
        self._conn.execute(
            "UPDATE memories SET deleted=1, updated_at=? WHERE id=?",
            (_now(), memory_id),
        )
        self._conn.commit()

    def purge_deleted(self) -> int:
        cur = self._conn.execute("DELETE FROM memories WHERE deleted=1")
        self._conn.commit()
        return cur.rowcount

    def query_memories(
        self,
        memory_type: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        sql = "SELECT * FROM memories WHERE deleted=0"
        args: list = []
        if memory_type:
            sql += " AND memory_type=?"
            args.append(memory_type)
        sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def all_rows(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE deleted=0 ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── associações ────────────────────────────────────────

    def add_association(self, mem_a: str, mem_b: str, rel: str, strength: float, notes: str = "") -> None:
        self._conn.execute(
            """INSERT INTO associations(memory_id, related_memory_id,
               relationship_type, strength, notes)
               VALUES (?,?,?,?,?)""",
            (mem_a, mem_b, rel, strength, notes),
        )
        self._conn.commit()

    def list_associations(self, memory_id: str) -> list[dict]:
        rows = self._conn.execute(
            """SELECT related_memory_id AS other, relationship_type,
                      strength, notes
               FROM associations WHERE memory_id=?
               UNION
               SELECT memory_id AS other, relationship_type, strength, notes
               FROM associations WHERE related_memory_id=? AND relationship_type != 'contradicts'
            """,
            (memory_id, memory_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── working memory ─────────────────────────────────────

    def set_working_memory(self, slot: str, data: dict) -> None:
        self._conn.execute(
            """INSERT INTO working_memory(slot, goal, entities, constraints,
               status, steps, results, updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(slot) DO UPDATE SET
                 goal=excluded.goal, entities=excluded.entities,
                 constraints=excluded.constraints, status=excluded.status,
                 steps=excluded.steps, results=excluded.results,
                 updated_at=excluded.updated_at""",
            (
                slot, data.get("goal", ""),
                json.dumps(data.get("entities", []), ensure_ascii=False),
                json.dumps(data.get("constraints", []), ensure_ascii=False),
                data.get("status", "active"),
                json.dumps(data.get("steps", []), ensure_ascii=False),
                json.dumps(data.get("results", []), ensure_ascii=False),
                _now(),
            ),
        )
        self._conn.commit()

    def get_working_memory(self, slot: str = "default") -> dict | None:
        r = self._conn.execute(
            "SELECT * FROM working_memory WHERE slot=?", (slot,)
        ).fetchone()
        if not r:
            return None
        return {
            "goal": r["goal"],
            "entities": _unjson(r["entities"]),
            "constraints": _unjson(r["constraints"]),
            "status": r["status"],
            "steps": _unjson(r["steps"]),
            "results": _unjson(r["results"]),
            "updated_at": r["updated_at"],
        }

    def clear_working_memory(self, slot: str = "default") -> None:
        self._conn.execute(
            "DELETE FROM working_memory WHERE slot=?", (slot,)
        )
        self._conn.commit()

    # ── conversas ──────────────────────────────────────────

    def add_conversation(self, conv_id: str, user_text: str, ai_text: str, importance: float, entities: list[str]) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO conversations
               (id, user_text, ai_text, importance, entities, created_at, processed)
               VALUES (?,?,?,?,?,?,0)""",
            (conv_id, user_text, ai_text, importance,
             json.dumps(entities, ensure_ascii=False), _now()),
        )
        self._conn.commit()

    def unprocessed_conversations(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM conversations WHERE processed=0 ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_conversation_processed(self, conv_id: str) -> None:
        self._conn.execute(
            "UPDATE conversations SET processed=1 WHERE id=?", (conv_id,)
        )
        self._conn.commit()

    # ── backup / corrupção ─────────────────────────────────

    def backup(self) -> Path:
        """Faz um snapshot versionado do banco (nunca sobrescreve)."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.backups_dir / f"aris_memory_{ts}.db"
        self._conn.commit()
        connection = sqlite3.connect(str(self.db_path))
        backup_conn = sqlite3.connect(str(dest))
        connection.backup(backup_conn)
        backup_conn.close()
        connection.close()
        self._cleanup_old_backups()
        return dest

    def _cleanup_old_backups(self, keep: int = 7) -> None:
        backups = sorted(self.backups_dir.glob("aris_memory_*.db"))
        for old in backups[:-keep]:
            old.unlink(missing_ok=True)

    def recover_from_backup(self) -> bool:
        """Restaura o backup mais recente preservando o original corrompido."""
        backups = sorted(self.backups_dir.glob("aris_memory_*.db"))
        if not backups:
            return False
        latest = backups[-1]
        corrupt_path = self.db_path.with_name(
            f"aris_memory_corrupt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )
        shutil.copy2(self.db_path, corrupt_path)
        shutil.copy2(latest, self.db_path)
        return self.integrity_ok()


def _now() -> str:
    from datetime import datetime
    return datetime.now(UTC).isoformat()


def _unjson(value: str | None) -> list:
    if not value:
        return []
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return []
