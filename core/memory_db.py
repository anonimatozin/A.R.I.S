"""Banco de dados SQLite unificado do A.R.I.S.

Fornece armazenamento persistente para MemoryManager, KnowledgeGraph
e Neural Memory System (Episodic/Procedural) num único arquivo:
``D:\\ARIS_MEMORY\\aris_memory.db``.

Schema:
- memory_entries : memórias do MemoryManager (14 categorias + memory_type)
- entities       : entidades do KnowledgeGraph
- relations      : relacionamentos entre entidades
- facts          : fatos sobre entidades
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_DEFAULT_DB_NAME = "aris_memory.db"


def _resolve_db_dir() -> Path:
    """Resolve o diretório do banco SQLite.

    Prioridade:
    1. Variável de ambiente ARIS_MEMORY_DIR
    2. D:\\ARIS_MEMORY\\ (drive dedicado)
    3. Fallback: <projeto>/data/memory/ (se D: não existir)
    """
    env = os.getenv("ARIS_MEMORY_DIR", "")
    if env:
        return Path(env)

    primary = Path("D:/ARIS_MEMORY")
    if primary.parent.exists():  # Verifica se o drive D: existe
        return primary

    # Fallback: dentro do projeto
    return Path(__file__).resolve().parent.parent / "data" / "memory"


class MemoryDB:
    """Camada de acesso SQLite thread-safe para toda a memória do A.R.I.S."""

    def __init__(self, db_dir: Path | None = None, logger: Any = None) -> None:
        self._logger = logger
        self._db_dir = db_dir or _resolve_db_dir()
        self._db_path = self._db_dir / _DEFAULT_DB_NAME
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._ensure_dir()
        self._connect()
        self._create_tables()

    # ── Conexão ────────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        self._db_dir.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> None:
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _execute(self, sql: str, params: tuple = (), *, fetch: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(sql, params)
            if fetch:
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            self._conn.commit()
            return []

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── Schema ─────────────────────────────────────────────────

    def _create_tables(self) -> None:
        self._execute("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 5,
                priority TEXT NOT NULL DEFAULT 'Média',
                tags TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT 'conversation',
                memory_type TEXT NOT NULL DEFAULT 'semantic',
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                is_permanente INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{}',
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'knowledge_graph',
                created_at TEXT NOT NULL
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{}',
                weight REAL NOT NULL DEFAULT 1.0,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'knowledge_graph',
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES entities(id),
                FOREIGN KEY (target_id) REFERENCES entities(id)
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'knowledge_graph',
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (entity_id) REFERENCES entities(id)
            )
        """)
        self._execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_category
            ON memory_entries(category)
        """)
        self._execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_source
            ON memory_entries(source)
        """)
        self._execute("""
            CREATE INDEX IF NOT EXISTS idx_entities_name
            ON entities(name)
        """)
        self._execute("""
            CREATE INDEX IF NOT EXISTS idx_relations_source
            ON relations(source_id)
        """)
        self._execute("""
            CREATE INDEX IF NOT EXISTS idx_relations_target
            ON relations(target_id)
        """)
        self._execute("""
            CREATE INDEX IF NOT EXISTS idx_facts_entity
            ON facts(entity_id)
        """)

    # ── memory_entries CRUD ────────────────────────────────────

    def insert_memory(self, data: dict[str, Any]) -> None:
        self._execute(
            """INSERT OR REPLACE INTO memory_entries
               (id, category, title, content, importance, priority, tags,
                source, memory_type, created_at, last_accessed, access_count, is_permanente)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data["category"],
                data["title"],
                data["content"],
                data["importance"],
                data["priority"],
                data.get("tags", "[]"),
                data.get("source", "conversation"),
                data.get("memory_type", "semantic"),
                data["created_at"],
                data["last_accessed"],
                data.get("access_count", 0),
                1 if data.get("is_permanente") else 0,
            ),
        )

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        rows = self._execute(
            "SELECT * FROM memory_entries WHERE id = ?",
            (memory_id,),
            fetch=True,
        )
        return rows[0] if rows else None

    def search_memories(
        self,
        query: str = "",
        category: str | None = None,
        min_importance: int = 0,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if query:
            # Escapar wildcards LIKE para prevenir LIKE injection
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')")
            q = f"%{escaped}%"
            params.extend([q, q])
        if category:
            conditions.append("category = ?")
            params.append(category)
        if min_importance > 0:
            conditions.append("importance >= ?")
            params.append(min_importance)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM memory_entries {where} ORDER BY importance DESC, access_count DESC LIMIT ?"
        params.append(limit)

        rows = self._execute(sql, tuple(params), fetch=True)

        if tags:
            filtered = []
            for r in rows:
                try:
                    import json
                    entry_tags = json.loads(r.get("tags", "[]"))
                    if any(t in entry_tags for t in tags):
                        filtered.append(r)
                except Exception:
                    pass
            return filtered[:limit]

        return rows

    def update_memory(self, memory_id: str, **kwargs: Any) -> dict[str, Any] | None:
        existing = self.get_memory(memory_id)
        if not existing:
            return None

        field_map = {
            "title": "title",
            "content": "content",
            "importance": "importance",
            "priority": "priority",
            "tags": "tags",
            "source": "source",
            "memory_type": "memory_type",
            "last_accessed": "last_accessed",
            "access_count": "access_count",
            "is_permanente": "is_permanente",
        }

        set_clauses: list[str] = []
        values: list[Any] = []
        for key, value in kwargs.items():
            col = field_map.get(key)
            if col:
                set_clauses.append(f"{col} = ?")
                if key == "is_permanente":
                    values.append(1 if value else 0)
                else:
                    values.append(value)

        if not set_clauses:
            return existing

        values.append(memory_id)
        self._execute(
            f"UPDATE memory_entries SET {', '.join(set_clauses)} WHERE id = ?",
            tuple(values),
        )
        return self.get_memory(memory_id)

    def delete_memory(self, memory_id: str) -> bool:
        rows = self._execute(
            "SELECT id FROM memory_entries WHERE id = ?",
            (memory_id,),
            fetch=True,
        )
        if not rows:
            return False
        self._execute("DELETE FROM memory_entries WHERE id = ?", (memory_id,))
        return True

    def count_memories(self) -> int:
        rows = self._execute("SELECT COUNT(*) as cnt FROM memory_entries", fetch=True)
        return rows[0]["cnt"] if rows else 0

    def get_all_memories(self) -> list[dict[str, Any]]:
        return self._execute("SELECT * FROM memory_entries ORDER BY created_at", fetch=True)

    # ── entities CRUD ──────────────────────────────────────────

    def insert_entity(self, data: dict[str, Any]) -> None:
        self._execute(
            """INSERT OR REPLACE INTO entities
               (id, name, entity_type, properties, confidence, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data["name"],
                data["entity_type"],
                data.get("properties", "{}"),
                data.get("confidence", 1.0),
                data.get("source", "knowledge_graph"),
                data.get("created_at", datetime.now().isoformat()),
            ),
        )

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        rows = self._execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,), fetch=True
        )
        return rows[0] if rows else None

    def search_entities(self, name: str = "", entity_type: str = "", limit: int = 50) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if name:
            conditions.append("name LIKE ?")
            params.append(f"%{name}%")
        if entity_type:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM entities {where} LIMIT ?"
        params.append(limit)
        return self._execute(sql, tuple(params), fetch=True)

    def delete_entity(self, entity_id: str) -> bool:
        rows = self._execute(
            "SELECT id FROM entities WHERE id = ?", (entity_id,), fetch=True
        )
        if not rows:
            return False
        self._execute("DELETE FROM facts WHERE entity_id = ?", (entity_id,))
        self._execute(
            "DELETE FROM relations WHERE source_id = ? OR target_id = ?",
            (entity_id, entity_id),
        )
        self._execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        return True

    # ── relations CRUD ─────────────────────────────────────────

    def insert_relation(self, data: dict[str, Any]) -> None:
        self._execute(
            """INSERT OR REPLACE INTO relations
               (id, source_id, target_id, relation_type, properties, weight, confidence, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data["source_id"],
                data["target_id"],
                data["relation_type"],
                data.get("properties", "{}"),
                data.get("weight", 1.0),
                data.get("confidence", 1.0),
                data.get("source", "knowledge_graph"),
                data.get("created_at", datetime.now().isoformat()),
            ),
        )

    def get_relation(self, relation_id: str) -> dict[str, Any] | None:
        rows = self._execute(
            "SELECT * FROM relations WHERE id = ?", (relation_id,), fetch=True
        )
        return rows[0] if rows else None

    def search_relations(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)
        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)
        if relation_type:
            conditions.append("relation_type = ?")
            params.append(relation_type)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM relations {where} LIMIT ?"
        params.append(limit)
        return self._execute(sql, tuple(params), fetch=True)

    def delete_relation(self, relation_id: str) -> bool:
        rows = self._execute(
            "SELECT id FROM relations WHERE id = ?", (relation_id,), fetch=True
        )
        if not rows:
            return False
        self._execute("DELETE FROM relations WHERE id = ?", (relation_id,))
        return True

    # ── facts CRUD ─────────────────────────────────────────────

    def insert_fact(self, data: dict[str, Any]) -> None:
        self._execute(
            """INSERT OR REPLACE INTO facts
               (id, entity_id, content, source, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data["entity_id"],
                data["content"],
                data.get("source", "knowledge_graph"),
                data.get("confidence", 1.0),
                data.get("created_at", datetime.now().isoformat()),
            ),
        )

    def get_fact(self, fact_id: str) -> dict[str, Any] | None:
        rows = self._execute(
            "SELECT * FROM facts WHERE id = ?", (fact_id,), fetch=True
        )
        return rows[0] if rows else None

    def search_facts(self, entity_id: str | None = None, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if entity_id:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM facts {where} LIMIT ?"
        params.append(limit)
        return self._execute(sql, tuple(params), fetch=True)

    def delete_fact(self, fact_id: str) -> bool:
        rows = self._execute(
            "SELECT id FROM facts WHERE id = ?", (fact_id,), fetch=True
        )
        if not rows:
            return False
        self._execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        return True

    # ── Estatísticas ───────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        mem_count = self.count_memories()
        ent_count = self._execute("SELECT COUNT(*) as cnt FROM entities", fetch=True)[0]["cnt"]
        rel_count = self._execute("SELECT COUNT(*) as cnt FROM relations", fetch=True)[0]["cnt"]
        fact_count = self._execute("SELECT COUNT(*) as cnt FROM facts", fetch=True)[0]["cnt"]

        categories = self._execute(
            "SELECT category, COUNT(*) as cnt FROM memory_entries GROUP BY category",
            fetch=True,
        )

        return {
            "total_memories": mem_count,
            "total_entities": ent_count,
            "total_relations": rel_count,
            "total_facts": fact_count,
            "by_category": {r["category"]: r["cnt"] for r in categories},
        }
