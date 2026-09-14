import sqlite3
import os
from datetime import datetime, timezone

BASE_DIR = os.path.expanduser("~/cll1")
DB_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "aris.db")


class ARISMemory:
    def __init__(self):
        os.makedirs(DB_DIR, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    importance INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    data TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def add_memory(self, content, category="general", importance=1):
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO memories
                (content, category, importance, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (content, category, importance, now, now))

            return cursor.lastrowid

    def get_memories(self, limit=20):
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM memories
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [dict(row) for row in rows]

    def search_memories(self, query, limit=20):
        pattern = f"%{query}%"

        with self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM memories
                WHERE content LIKE ?
                   OR category LIKE ?
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
            """, (pattern, pattern, limit)).fetchall()

            return [dict(row) for row in rows]

    def add_conversation(self, source, role, content):
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO conversations
                (source, role, content, created_at)
                VALUES (?, ?, ?, ?)
            """, (source, role, content, now))

            return cursor.lastrowid

    def set_knowledge(self, key, value):
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute("""
                INSERT INTO knowledge
                (key, value, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (key, value, now, now))

    def get_knowledge(self, key):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT value
                FROM knowledge
                WHERE key = ?
            """, (key,)).fetchone()

            return row["value"] if row else None

    def add_event(self, event_type, data=""):
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO events
                (event_type, data, created_at)
                VALUES (?, ?, ?)
            """, (event_type, data, now))

            return cursor.lastrowid

    def set_state(self, key, value):
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute("""
                INSERT INTO system_state
                (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (key, value, now))

    def get_state(self, key):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT value
                FROM system_state
                WHERE key = ?
            """, (key,)).fetchone()

            return row["value"] if row else None


if __name__ == "__main__":
    memory = ARISMemory()

    memory.add_memory(
        "Sistema de memória compartilhada da A.R.I.S. iniciado.",
        "system",
        10
    )

    print("A.R.I.S. Memory OK")
    print(f"Banco: {DB_PATH}")
    print(f"Memórias: {len(memory.get_memories())}")