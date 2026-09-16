"""Memory/state database operations."""

from __future__ import annotations

import os
import sqlite3
import time


class MemoryDB:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, timeout=30)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._init_tables()
        return self._conn

    def _init_tables(self) -> None:
        conn = self._conn
        if conn is None:
            return
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                importance INTEGER DEFAULT 5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()

    def add_memory(self, content: str, category: str = "general", importance: int = 5) -> dict:
        conn = self._get_conn()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cursor = conn.execute(
            "INSERT INTO memories (content, category, importance, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (content, category, importance, now, now),
        )
        conn.commit()
        return {"ok": True, "id": cursor.lastrowid}

    def get_memories(self, limit: int = 10) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT id, content, category, importance, created_at FROM memories ORDER BY importance DESC, created_at DESC LIMIT ?",
            (min(max(limit, 1), 100),),
        )
        return [dict(row) for row in cursor.fetchall()]

    def search_memories(self, query: str, limit: int = 20) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT id, content, category, importance, created_at FROM memories WHERE content LIKE ? OR category LIKE ? ORDER BY importance DESC LIMIT ?",
            (f"%{query[:50]}%", f"%{query[:50]}%", min(max(limit, 1), 100)),
        )
        return [dict(row) for row in cursor.fetchall()]

    def set_state(self, key: str, value: str) -> dict:
        conn = self._get_conn()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            "INSERT INTO system_state (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now),
        )
        conn.commit()
        return {"ok": True, "key": key}

    def get_state(self, key: str) -> dict | None:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT value, updated_at FROM system_state WHERE key = ?", (key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {"key": key, "value": row["value"], "updated_at": row["updated_at"]}

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
