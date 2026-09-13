"""Migração da memória atual (data/memory) para o novo SQLite.

Lê ``memory_index.json``, episódicas e procedurais existentes e
converte em memórias do banco. NUNCA apaga os originais: antes de
migrar, cria uma cópia em ``backups/legacy-<timestamp>``.
Só roda uma vez (marcado na meta table).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from .db import MemoryDatabase
from .models import MemoryKind, StorageClass

# Mapeiam as categorias do MemoryEntry legado para tipos cognitivos.
_CATEGORY_MAP = {
    "profile": MemoryKind.SEMANTIC,
    "config": MemoryKind.SEMANTIC,
    "devices": MemoryKind.SEMANTIC,
    "knowledge": MemoryKind.SEMANTIC,
    "projects": MemoryKind.SEMANTIC,
    "conversations": MemoryKind.CONVERSATION,
    "archive": MemoryKind.SEMANTIC,
}


# Diretórios criados pelo novo sistema dentro do mesmo root (data/memory):
# NUNCA copiá-los para o backup do legado (evita recursão/duplicação).
_LEGACY_EXCLUDE = {
    "database", "backups", "Backups", "semantic", "embeddings",
    "indexes", "metadata", "snapshots", "files", "experiences",
}


def migrate_legacy(db: MemoryDatabase, legacy_dir: Path,
                   logger=None) -> dict[str, int]:
    """Migra data/memory para o banco. Retorna contadores."""
    stats = {"memories": 0, "episodic": 0, "procedural": 0, "skipped": 0}
    if db.get_meta("migrated", "") == "yes":
        return {"already": 1}

    if not legacy_dir.exists():
        db.set_meta("migrated", "yes")
        return stats

    # Backup dos originais antes de qualquer coisa (ignora o próprio
    # backup e as pastas do novo sistema para não se auto-copiar).
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    legacy_backup = db.backups_dir / f"legacy-{ts}"
    shutil.copytree(
        legacy_dir, legacy_backup, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*_LEGACY_EXCLUDE),
    )

    index_path = legacy_dir / "Index" / "memory_index.json"
    if index_path.exists():
        try:
            with open(index_path, encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("memories", []):
                ok = _import_entry(db, entry)
                stats["memories" if ok else "skipped"] += 1
        except Exception as e:
            if logger:
                logger.error(f"Migração: índice inválido ({e})")
            stats["skipped"] += 1

    episodes = legacy_dir / "Episodic" / "episodes.json"
    if episodes.exists():
        try:
            with open(episodes, encoding="utf-8") as f:
                data = json.load(f)
            for item in data if isinstance(data, list) else data.get("episodes", []):
                if _import_json_item(db, item, MemoryKind.EPISODIC, "episodic"):
                    stats["episodic"] += 1
        except Exception as e:
            if logger:
                logger.error(f"Migração: episódicas inválidas ({e})")

    procedures = legacy_dir / "Procedural" / "procedures.json"
    if procedures.exists():
        try:
            with open(procedures, encoding="utf-8") as f:
                data = json.load(f)
            for item in data if isinstance(data, list) else data.get("procedures", []):
                if _import_json_item(db, item, MemoryKind.PROCEDURAL, "procedural"):
                    stats["procedural"] += 1
        except Exception as e:
            if logger:
                logger.error(f"Migração: procedurais inválidas ({e})")

    db.set_meta("migrated", "yes")
    db.set_meta("legacy_backup", str(legacy_backup))
    return stats


def _import_entry(db: MemoryDatabase, entry: dict) -> bool:
    content = entry.get("content") or entry.get("title") or ""
    if not content:
        return False
    cat = str(entry.get("category", "")).lower()
    kind = _CATEGORY_MAP.get(cat, MemoryKind.SEMANTIC)
    storage = _storage_from(cat, entry.get("is_permanente"))
    tags = entry.get("tags") or []
    entities = entry.get("entities") or []
    importance = float(entry.get("importance", 5))
    db.insert_memory(_row(
        kind, content, entry.get("title", "") or summary_of(content),
        storage, importance, entry.get("source", "legacy"),
        tags, entities, entry.get("id", "") or _new_id(db),
        entry.get("created_at") or _now(),
    ))
    return True


def _import_json_item(db: MemoryDatabase, item, kind: MemoryKind, source: str) -> bool:
    content = item.get("content") or item.get("description") or item.get("event") or item.get("title")
    if not content:
        return False
    tags = item.get("tags") or []
    db.insert_memory(_row(
        kind, content, item.get("title", "") or summary_of(content),
        StorageClass.NORMAL, float(item.get("importance", 5)),
        source, tags, item.get("entities") or [],
        item.get("id", "") or _new_id(db), item.get("created_at") or _now(),
    ))
    return True


def _row(kind, content, summary, storage, importance, source, tags, entities,
         memory_id, created_at) -> tuple:
    import json as _j
    return (
        memory_id, kind.value, storage.value, content, summary,
        created_at, created_at, created_at, importance, 0.7, source,
        _j.dumps(tags, ensure_ascii=False), _j.dumps(entities, ensure_ascii=False),
        0, 0, None,
    )


def _storage_from(cat: str, is_perma) -> StorageClass:
    if str(is_perma).lower() in ("1", "true") or cat in ("profile", "config"):
        return StorageClass.CRITICAL
    if cat in ("projects", "devices"):
        return StorageClass.IMPORTANT
    if cat == "conversations":
        return StorageClass.TEMPORARY
    return StorageClass.NORMAL


def summary_of(content: str) -> str:
    return " ".join(content.split())[:140]


def _new_id(db: MemoryDatabase) -> str:
    import uuid
    mid = uuid.uuid4().hex[:8]
    db.set_meta("last_id", mid)
    return mid


def _now() -> str:
    return datetime.now().astimezone().isoformat()
