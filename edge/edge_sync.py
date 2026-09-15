"""Sync client para a instância edge (CLL1).

Envia eventos pendentes ao PC quando volta online,
recebe atualizações do PC, e faz merge local.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("aris.edge.sync")

SYNC_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    row_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    data TEXT,
    created_at TEXT NOT NULL,
    synced_to_pc INTEGER DEFAULT 0,
    synced_at TEXT
)
"""


@dataclass
class SyncResult:
    success: bool = True
    pushed: int = 0
    received: int = 0
    error: str = ""


class EdgeSync:
    """Cliente de sincronização para o CLL1."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path).expanduser()
        self._conn: sqlite3.Connection | None = None
        self._last_sync: str = ""

    def boot(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(SYNC_LOG_TABLE)
        self._conn.commit()
        logger.info(f"EdgeSync: DB={self._db_path}")

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    def record_local_change(
        self, table_name: str, row_id: str, operation: str, data: dict
    ) -> None:
        if not self._conn:
            return
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._conn.execute(
            "INSERT INTO sync_log (table_name, row_id, operation, data, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (table_name, row_id, operation, json.dumps(data, default=str), ts),
        )
        self._conn.commit()

    def get_pending_events(self) -> list[dict]:
        if not self._conn:
            return []
        rows = self._conn.execute(
            "SELECT id, table_name, row_id, operation, data, created_at "
            "FROM sync_log WHERE synced_to_pc = 0 ORDER BY created_at"
        ).fetchall()
        events = []
        for r in rows:
            events.append({
                "id": r[0],
                "table_name": r[1],
                "row_id": r[2],
                "operation": r[3],
                "data": json.loads(r[4]) if r[4] else {},
                "created_at": r[5],
            })
        return events

    def mark_pushed(self, event_ids: list[int]) -> None:
        if not self._conn or not event_ids:
            return
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        placeholders = ",".join(["?"] * len(event_ids))
        self._conn.execute(
            f"UPDATE sync_log SET synced_to_pc = 1, synced_at = ? "
            f"WHERE id IN ({placeholders})",
            [ts, *event_ids],
        )
        self._conn.commit()

    def receive_from_pc(self, events: list[dict]) -> int:
        if not events:
            return 0

        imported = 0
        for ev in events:
            table = ev.get("table_name", "")
            op = ev.get("operation", "")
            row_id = ev.get("row_id", "")
            data = ev.get("data", {})

            if not table or not op:
                continue

            try:
                if op in ("insert", "update"):
                    self._upsert_local(table, row_id, data)
                    imported += 1
                elif op == "delete":
                    self._delete_local(table, row_id)
                    imported += 1
            except Exception as e:
                logger.warning(f"EdgeSync: erro ao importar {table}/{row_id}: {e}")

        if imported > 0:
            self._conn.commit()

        self._last_sync = time.strftime("%Y-%m-%dT%H:%M:%S")
        return imported

    def _upsert_local(self, table: str, row_id: str, data: dict) -> None:
        if not self._conn:
            return
        try:
            cols = list(data.keys())
            vals = list(data.values())
            if "id" not in cols:
                cols.insert(0, "id")
                vals.insert(0, row_id)
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            self._conn.execute(
                f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})",
                vals,
            )
        except sqlite3.OperationalError:
            pass

    def _delete_local(self, table: str, row_id: str) -> None:
        if not self._conn:
            return
        try:
            self._conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        except sqlite3.OperationalError:
            pass

    def search_memories(self, query: str, limit: int = 5) -> list[dict]:
        if not self._conn:
            return []
        try:
            rows = self._conn.execute(
                "SELECT id, content, category, importance, created_at "
                "FROM memories WHERE content LIKE ? "
                "ORDER BY importance DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            return [
                {"id": r[0], "content": r[1], "category": r[2],
                 "importance": r[3], "created_at": r[4]}
                for r in rows
            ]
        except sqlite3.OperationalError:
            return []

    def remember(self, content: str, category: str = "general",
                 importance: int = 5, tags: list[str] | None = None) -> str:
        if not self._conn:
            return ""
        row_id = f"edge_{int(time.time() * 1000)}"
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            self._conn.execute(
                "INSERT INTO memories (id, content, category, importance, tags, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row_id, content, category, importance, json.dumps(tags or []), ts, ts),
            )
            self._conn.commit()
            self.record_local_change("memories", row_id, "insert", {
                "id": row_id, "content": content, "category": category,
                "importance": importance, "tags": json.dumps(tags or []),
                "created_at": ts, "updated_at": ts,
            })
            return row_id
        except sqlite3.OperationalError as e:
            logger.warning(f"EdgeSync: remember falhou: {e}")
            return ""

    def get_stats(self) -> dict:
        stats: dict[str, Any] = {"db": str(self._db_path), "last_sync": self._last_sync}
        if self._conn:
            try:
                cur = self._conn.execute(
                    "SELECT COUNT(*) FROM sync_log WHERE synced_to_pc = 0"
                )
                stats["pending_sync"] = cur.fetchone()[0]
            except sqlite3.OperationalError:
                stats["pending_sync"] = 0
        return stats
