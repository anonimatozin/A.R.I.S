"""Sync Engine — sincronizacao de memoria entre PC e CLL1.

Gerencia sync log, merge por timestamp (last-write-wins),
e backup antes de merge.
Também sincroniza personalidade entre PC (Primary), CLL1 (Edge) e painel web.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from utils.logger import Logger


class SyncEngine:
    """Engine de sincronizacao de memoria bidirecional.

    Args:
        db_path: Caminho para o SQLite de memoria do PC.
        logger: Logger opcional.
    """

    def __init__(
        self,
        db_path: Path | str = "D:/ARIS_MEMORY/database/aris_memory.db",
        logger: Logger | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._logger = logger
        self._last_sync: str = ""
        self._personality_hash: str = ""

    @property
    def last_sync(self) -> str:
        return self._last_sync

    @property
    def personality_hash(self) -> str:
        return self._personality_hash

    def compute_personality_hash(self, personality: str) -> str:
        """Computa hash da personalidade para detectar mudanças."""
        import hashlib
        return hashlib.sha256(personality.encode()).hexdigest()[:16]

    def backup_before_sync(self) -> Path | None:
        """Cria backup do SQLite antes de sincronizar."""
        if not self._db_path.exists():
            return None

        backup_dir = self._db_path.parent.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"pre_sync_{ts}.db"

        try:
            shutil.copy2(self._db_path, backup_path)
            if self._logger:
                self._logger.info(f"Backup criado: {backup_path}")
            return backup_path
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Backup falhou: {e}")
            return None

    def get_pending_since(self, since: str) -> list[dict]:
        """Retorna registros novos desde um timestamp.

        Args:
            since: ISO timestamp da ultima sync.

        Returns:
            Lista de dicts com dados para sync.
        """
        if not self._db_path.exists():
            return []

        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row

            if since:
                cursor = conn.execute(
                    "SELECT id, memory_type, content, summary, importance, "
                    "confidence, source, tags, entities, created_at, updated_at "
                    "FROM memories WHERE created_at > ? AND deleted = 0 "
                    "ORDER BY created_at ASC LIMIT 500",
                    (since,),
                )
            else:
                cursor = conn.execute(
                    "SELECT id, memory_type, content, summary, importance, "
                    "confidence, source, tags, entities, created_at, updated_at "
                    "FROM memories WHERE deleted = 0 "
                    "ORDER BY created_at ASC LIMIT 500"
                )

            records = []
            for row in cursor.fetchall():
                rec = dict(row)
                for key in ("tags", "entities"):
                    if rec.get(key) and isinstance(rec[key], str):
                        try:
                            rec[key] = json.loads(rec[key])
                        except (json.JSONDecodeError, TypeError):
                            rec[key] = []
                records.append(rec)

            conn.close()
            return records

        except Exception as e:
            if self._logger:
                self._logger.warning(f"get_pending_since erro: {e}")
            return []

    def merge_records(self, records: list[dict], source: str = "cll1") -> int:
        """Importa registros de outra instancia com last-write-wins.

        Args:
            records: Lista de registros para importar.
            source: Origem dos registros (para logging).

        Returns:
            Numero de registros importados.
        """
        if not records:
            return 0

        if not self._db_path.exists():
            if self._logger:
                self._logger.warning("DB nao existe, impossivel importar")
            return 0

        try:
            conn = sqlite3.connect(str(self._db_path))
            imported = 0

            for rec in records:
                rec_id = rec.get("id", "")
                if not rec_id:
                    continue

                existing = conn.execute(
                    "SELECT updated_at FROM memories WHERE id = ?",
                    (rec_id,),
                ).fetchone()

                if existing:
                    existing_ts = existing[0] or ""
                    new_ts = rec.get("updated_at", "")
                    if new_ts > existing_ts:
                        conn.execute(
                            "UPDATE memories SET content = ?, importance = ?, "
                            "updated_at = ? WHERE id = ?",
                            (
                                rec.get("content", ""),
                                rec.get("importance", 5),
                                new_ts,
                                rec_id,
                            ),
                        )
                        imported += 1
                else:
                    tags = rec.get("tags", [])
                    entities = rec.get("entities", [])
                    conn.execute(
                        "INSERT OR IGNORE INTO memories "
                        "(id, memory_type, content, summary, importance, "
                        "confidence, source, tags, entities, created_at, "
                        "updated_at, deleted) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                        (
                            rec_id,
                            rec.get("memory_type", "semantic"),
                            rec.get("content", ""),
                            rec.get("summary", ""),
                            rec.get("importance", 5),
                            rec.get("confidence", 0.7),
                            rec.get("source", source),
                            json.dumps(tags, ensure_ascii=False),
                            json.dumps(entities, ensure_ascii=False),
                            rec.get("created_at", datetime.now(UTC).isoformat()),
                            rec.get("updated_at", datetime.now(UTC).isoformat()),
                        ),
                    )
                    imported += 1

            conn.commit()
            conn.close()

            self._last_sync = datetime.now(UTC).isoformat()

            if self._logger:
                self._logger.info(
                    f"Sync concluida: {imported}/{len(records)} registros "
                    f"importados de {source}"
                )

            return imported

        except Exception as e:
            if self._logger:
                self._logger.warning(f"merge_records erro: {e}")
            return 0

    # ── Personality Sync ────────────────────────────────────────

    def get_personality_for_sync(self, personality: str) -> dict:
        """Prepara personalidade para envio ao CLL1/painel web."""
        return {
            "personality": personality,
            "hash": self.compute_personality_hash(personality),
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "pc_primary",
        }

    def apply_personality_sync(self, sync_data: dict) -> bool:
        """Aplica personalidade recebida do PC (para CLL1/Edge)."""
        try:
            personality = sync_data.get("personality", "")
            if not personality:
                return False

            # Salvar no arquivo de personalidade sincronizada
            personality_path = Path("~/cll1/data/personality_sync.md").expanduser()
            personality_path.parent.mkdir(parents=True, exist_ok=True)
            personality_path.write_text(personality, encoding="utf-8")

            self._personality_hash = sync_data.get("hash", "")
            if self._logger:
                self._logger.info(f"Personalidade sincronizada recebida (hash: {self._personality_hash})")
            return True
        except Exception as e:
            if self._logger:
                self._logger.warning(f"apply_personality_sync erro: {e}")
            return False
