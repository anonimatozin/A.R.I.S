"""MemoryService: serviço central de memória cognitiva da ARIS.

A ARIS acessa a memória através deste serviço (mais o acesso legado
existente, que permanece compatível). Não há SQL espalhado por handlers.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .associations import associate, related_memories
from .backup import MemoryBackup
from .consolidator import consolidate
from .db import MemoryDatabase
from .decay import apply_decay, touch
from .decay import reinforce as _reinforce
from .migrate import migrate_legacy
from .models import MemoryItem, MemoryKind, StorageClass
from .paths import memory_layout, resolve_memory_root
from .retriever import retrieve as _retrieve
from .texting import extract_entities


class MemoryService:
    """Facade sobre o banco SQLite + subsistemas cognitivos."""

    def __init__(
        self,
        primary_root=None,
        fallback_root=None,
        legacy_dir=None,
        logger=None,
    ) -> None:
        self._logger = logger
        self._preferred = primary_root
        self.root, self.primary_available = resolve_memory_root(primary_root, fallback_root)
        self.layout = memory_layout(self.root)
        self._db = MemoryDatabase(
            db_path=self.layout["database"] / "aris_memory.db",
            backups_dir=self.layout["backups"],
        )
        self._backup = MemoryBackup(self._db)
        self.legacy_dir = legacy_dir

    # ── ciclo de vida ──────────────────────────────────────

    def boot(self) -> None:
        """Inicializa com segurança: integridade, migração e manutenção."""
        if not self._db.integrity_ok():
            self._log("Aviso: banco de memória corrompido. Tentando recuperar do backup.")
            if self._backup.recover():
                self._log("Memória recuperada a partir do backup.")
            else:
                self._log("Sem backup íntegro. Iniciando banco novo (original preservado).")
                self._db = self._backup.preserve_corrupt_and_reset()
                self._db.ensure_schema()

        if not self._db.get_meta("migrated", "") == "yes" and self.legacy_dir:
            stats = migrate_legacy(self._db, self.legacy_dir, self._logger)
            if stats:
                self._log(f"Migração da memória antiga: {stats}")

        if self._backup.due():
            dest = self._backup.snapshot()
            self._log(f"Backup da memória criado: {dest.name}")

        apply_decay(self._db)
        self._db.purge_deleted()
        self._sync_if_primary_back()

    def close(self) -> None:
        self._db.close()

    # ── API pública ────────────────────────────────────────

    def remember(self, content: str, kind: MemoryKind = MemoryKind.SEMANTIC,
                 storage: StorageClass = StorageClass.NORMAL, importance: float = 5.0,
                 confidence: float = 0.7, source: str = "user",
                 tags: list[str] | None = None, entities: list[str] | None = None,
                 summary: str = "") -> MemoryItem:
        mid = uuid.uuid4().hex[:8]
        now = _now()
        rows = (
            mid, kind.value, storage.value, content,
            summary or _summarize(content), now, now, now,
            max(1.0, min(10.0, importance)), max(0.0, min(1.0, confidence)),
            source, json.dumps(tags or [], ensure_ascii=False),
            json.dumps(entities or extract_entities(content), ensure_ascii=False),
            0, 0, None,
        )
        self._db.insert_memory(rows)
        return MemoryItem(
            id=mid, memory_type=kind, storage_class=storage, content=content,
            summary=summary or _summarize(content), importance=importance,
            confidence=confidence, source=source, tags=tags or [],
            entities=entities or extract_entities(content), created_at=now,
            updated_at=now, last_accessed=now,
        )

    def retrieve(self, query: str, context: dict | None = None,
                 limit: int = 10, kind: MemoryKind | None = None) -> list[dict]:
        return _retrieve(self._db, query, context, limit,
                         memory_type=(kind.value if kind else None))

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return self.retrieve(query, limit=limit)

    def update(self, memory_id: str, **fields) -> bool:
        allowed = {"content", "summary", "importance", "confidence",
                   "storage_class", "tags", "entities", "expiration"}
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return False
        clean["updated_at"] = _now()
        self._db.update_memory(memory_id, clean)
        return True

    def forget(self, memory_id: str) -> None:
        self._db.soft_delete(memory_id)

    def reinforce(self, memory_id: str, by: float = 1.0, up_conf: bool = True) -> None:
        _reinforce(self._db, memory_id, by=by, up_conf=up_conf)

    def touch(self, memory_id: str) -> None:
        touch(self._db, memory_id)

    def associate(self, memory_a, memory_b, relationship: str = "related_to",
                  strength: float = 0.8, notes: str = "") -> None:
        associate(self._db, memory_a, memory_b, relationship, strength, notes)

    def related(self, memory_id: str, depth: int = 2) -> list[str]:
        return related_memories(self._db, memory_id, depth)

    def create_episode(self, content: str, importance: float = 6.0,
                       storage: StorageClass = StorageClass.NORMAL) -> MemoryItem:
        return self.remember(content, MemoryKind.EPISODIC, storage, importance)

    def create_semantic_memory(self, content: str, importance: float = 6.0,
                               storage: StorageClass = StorageClass.IMPORTANT) -> MemoryItem:
        return self.remember(content, MemoryKind.SEMANTIC, storage, importance)

    def create_procedure(self, content: str, storage: StorageClass = StorageClass.IMPORTANT) -> MemoryItem:
        return self.remember(content, MemoryKind.PROCEDURAL, storage,
                             importance=7.0, source="procedural")

    # ── working memory ─────────────────────────────────────

    def get_working_memory(self, slot: str = "default") -> dict | None:
        return self._db.get_working_memory(slot)

    def set_working_memory(self, slot: str, goal: str = "", entities: list | None = None,
                           constraints: list | None = None, status: str = "active",
                           steps: list | None = None, results: list | None = None) -> None:
        self._db.set_working_memory(slot, {
            "goal": goal, "entities": entities or [], "constraints": constraints or [],
            "status": status, "steps": steps or [], "results": results or [],
        })

    def clear_working_memory(self, slot: str = "default") -> None:
        self._db.clear_working_memory(slot)

    # ── eventos / observação ───────────────────────────────

    def observe(self, event_type: str, payload: dict | None = None) -> None:
        """Recebe eventos (USER_MESSAGE, COMMAND_EXECUTED...).

        Alimenta o buffer de conversas; a consolidação é leve e não
        bloqueia o loop. O LLM nunca acessa o banco diretamente.
        """
        payload = payload or {}
        if event_type == "USER_MESSAGE":
            text = payload.get("text", "")
            if text and len(text.split()) >= 3:
                self._db.add_conversation(
                    uuid.uuid4().hex[:8], text, payload.get("response", ""),
                    float(payload.get("importance", 3.0)),
                    extract_entities(text),
                )
                self.consolidate()

    def consolidate(self) -> dict[str, int]:
        result = consolidate(self._db)
        return {"created": result.created, "reinforced": result.reinforced,
                "contradicted": result.contradicted, "episode": result.episode,
                "dropped": result.dropped}

    # ── manutenção ─────────────────────────────────────────

    def backup_now(self) -> str:
        dest = self._backup.snapshot()
        return str(dest)

    def get_stats(self) -> dict[str, Any]:
        stats = {"total": 0, "by_kind": {}, "primary": self.primary_available,
                 "root": str(self.root)}
        for row in self._db.query_memories(limit=10000):
            kind = row.get("memory_type", "?")
            stats["by_kind"][kind] = stats["by_kind"].get(kind, 0) + 1
            stats["total"] += 1
        return stats

    def get(self, memory_id: str) -> MemoryItem | None:
        row = self._db.get_memory(memory_id)
        if not row:
            return None
        return MemoryItem(
            id=row["id"], memory_type=MemoryKind(row["memory_type"]),
            storage_class=StorageClass(row["storage_class"]),
            content=row["content"], summary=row.get("summary", ""),
            importance=row.get("importance", 5.0), confidence=row.get("confidence", 0.7),
            source=row.get("source", ""), tags=_list(row.get("tags")),
            entities=_list(row.get("entities")),
            access_count=row.get("access_count", 0),
            reinforcement_count=row.get("reinforcement_count", 0),
            created_at=row.get("created_at"), updated_at=row.get("updated_at"),
            last_accessed=row.get("last_accessed"),
        )

    def _sync_if_primary_back(self) -> None:
        """Quando D: reaparece, copia o fallback para o primário (sem apagar nada)."""
        if self.primary_available:
            return
        try:
            preferred, available = resolve_memory_root(self._preferred)
            if not available or preferred == self.root:
                return
            new_db_path = preferred / "database" / "aris_memory.db"
            new_db_path.parent.mkdir(parents=True, exist_ok=True)
            if self._db.db_path.exists() and not new_db_path.exists():
                import shutil
                shutil.copy2(self._db.db_path, new_db_path)
            self._db.close()
            self._db = MemoryDatabase(new_db_path, preferred / "backups")
            self.root = preferred
            self.primary_available = True
            self._log("Memória sincronizada para o armazenamento primário.")
        except Exception as e:
            self._log(f"Falha ao sincronizar para o primário ({e})")

    def _log(self, msg: str) -> None:
        if self._logger:
            self._logger.info(msg)


def _summarize(text: str) -> str:
    return " ".join(text.split())[:140]


def _list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _now() -> str:
    return datetime.now(UTC).isoformat()
