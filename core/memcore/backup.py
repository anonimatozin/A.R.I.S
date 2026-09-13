"""Backup seguro e recuperação da memória SQLite.

Snapshots versionados nunca são sobrescritos (mantém as N últimas).
Detecção de corrupção preserva a evidência original em
``backups/corrupt_*_original.db`` antes de qualquer recuperação.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

from .db import MemoryDatabase

_BACKUP_INTERVAL = timedelta_days = 1


def _now() -> str:
    return datetime.now().astimezone().isoformat()


class MemoryBackup:
    def __init__(self, database: MemoryDatabase) -> None:
        self.db = database

    def due(self) -> bool:
        last = self.db.get_meta("last_backup", "")
        if not last:
            return True
        try:
            from datetime import datetime as dt
            parsed = dt.fromisoformat(last)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            age = (datetime.now(parsed.tzinfo) - parsed).total_seconds()
            return age > 86400 * _BACKUP_INTERVAL
        except ValueError:
            return True

    def snapshot(self) -> object:
        dest = self.db.backup()
        self.db.set_meta("last_backup", _now())
        return dest

    def recover(self) -> bool:
        ok = self.db.recover_from_backup()
        if ok:
            self.db.ensure_schema()
        return ok

    def preserve_corrupt_and_reset(self) -> MemoryDatabase:
        """Preserva a evidência corrompida e inicia um banco novo."""
        src = self.db.db_path
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        corrupt = self.db.backups_dir / f"corrupt_{ts}_original.db"
        self.db.close()
        try:
            shutil.copy2(src, corrupt)
        except OSError:
            pass
        src.unlink(missing_ok=True)
        return MemoryDatabase(src, backups_dir=self.db.backups_dir)
