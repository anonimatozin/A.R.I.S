"""Gerenciador de memória do A.R.I.S.

Sistema central de armazenamento, recuperação e busca de memórias.
Backend: SQLite via MemoryDB (substitui JSON index + arquivos avulsos).
"""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.memory_db import MemoryDB
from core.memory_models import MemoryCategory, MemoryEntry, Priority
from core.neural.events import (
    EVENT_MEMORY_CREATED,
    EVENT_MEMORY_DELETED,
    EVENT_MEMORY_RETRIEVED,
    EVENT_MEMORY_UPDATED,
    PRIORITY_LOW,
    Event,
)
from utils.logger import Logger


class MemoryManager:
    """Gerenciador central do sistema de memória.

    Responsável por armazenar, recuperar, buscar e gerenciar
    todas as memórias do A.R.I.S.

    Backend SQLite via MemoryDB. A API pública é idêntica à versão
    anterior (JSON) — consumidores não precisam mudar.
    """

    INDEX_FILE = "memory_index.json"
    METADATA_DIR = "Index"

    def __init__(self, logger: Logger, memory_root: Path | None = None,
                 db_dir: Path | None = None) -> None:
        """Inicializa o gerenciador de memória.

        Args:
            logger: Instância do logger.
            memory_root: Diretório raiz da memória (legado, para backups/organizer).
            db_dir: Diretório do banco SQLite. Se None, usa D:\\ARIS_MEMORY\\ (produção).
        """
        self._logger = logger
        self._memory_dir = memory_root or (
            Path(__file__).resolve().parent.parent / "data" / "memory"
        )
        # db_dir=None → produção (D:\ARIS_MEMORY\ via _resolve_db_dir)
        # db_dir=path → teste/isolamento
        self._db = MemoryDB(db_dir=db_dir, logger=logger)
        self._event_bus: Any = None

        # Migração: se existir índice JSON antigo, importar para SQLite
        self._migrate_from_json_if_needed()

    def set_event_bus(self, event_bus: Any) -> None:
        """Define o Event Bus para publicação de eventos de memória."""
        self._event_bus = event_bus

    def _emit(self, event_type: str, payload: dict) -> None:
        """Publica um evento no bus (se disponível)."""
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                Event(
                    event_type=event_type,
                    source="memory",
                    priority=PRIORITY_LOW,
                    confidence=1.0,
                    payload=payload,
                )
            )
        except Exception:
            pass

    # ── Migração JSON → SQLite ─────────────────────────────────

    def _migrate_from_json_if_needed(self) -> None:
        """Importa dados do JSON antigo para SQLite (uma única vez)."""
        index_path = self._memory_dir / self.METADATA_DIR / self.INDEX_FILE
        if not index_path.exists():
            return

        try:
            with open(index_path, encoding="utf-8") as f:
                data = json.load(f)
            memories = data.get("memories", [])
            if not memories:
                self._logger.info("Índice JSON vazio. Nada a migrar.")
                return

            count = 0
            for entry_data in memories:
                entry = MemoryEntry.from_dict(entry_data)
                self._db.insert_memory(self._entry_to_row(entry))
                count += 1

            self._logger.info(f"Migração JSON→SQLite concluída: {count} memórias importadas.")

            # Mover índice antigo para backup
            backup_dir = self._memory_dir / "_migrated_backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / self.INDEX_FILE
            if backup_path.exists():
                backup_path = backup_dir / f"{self.INDEX_FILE}.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            shutil.move(str(index_path), str(backup_path))
            self._logger.info(f"Índice JSON antigo movido para: {backup_path}")

        except Exception as e:
            self._logger.error(f"Erro na migração JSON→SQLite: {e}")

    # ── Conversão MemoryEntry ↔ Row ────────────────────────────

    @staticmethod
    def _entry_to_row(entry: MemoryEntry) -> dict:
        return {
            "id": entry.id,
            "category": entry.category.value,
            "title": entry.title,
            "content": entry.content,
            "importance": entry.importance,
            "priority": entry.priority.value,
            "tags": json.dumps(entry.tags, ensure_ascii=False),
            "source": entry.source,
            "memory_type": "semantic",
            "created_at": entry.created_at,
            "last_accessed": entry.last_accessed,
            "access_count": entry.access_count,
            "is_permanente": entry.is_permanente,
        }

    @staticmethod
    def _row_to_entry(row: dict) -> MemoryEntry:
        tags_raw = row.get("tags", "[]")
        try:
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
        except Exception:
            tags = []

        return MemoryEntry(
            id=row["id"],
            title=row["title"],
            content=row["content"],
            category=MemoryCategory(row["category"]),
            importance=row["importance"],
            priority=Priority(row["priority"]),
            tags=tags,
            source=row.get("source", "conversation"),
            created_at=row["created_at"],
            last_accessed=row["last_accessed"],
            access_count=row.get("access_count", 0),
            is_permanente=bool(row.get("is_permanente")),
        )

    # ── API pública (idêntica à versão JSON) ───────────────────

    def save(
        self,
        title: str,
        content: str,
        category: MemoryCategory = MemoryCategory.KNOWLEDGE,
        importance: int = 5,
        priority: Priority = Priority.MEDIUM,
        tags: list[str] | None = None,
        source: str = "conversation",
        is_permanente: bool = False,
    ) -> MemoryEntry:
        """Salva uma nova memória."""
        entry_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        entry = MemoryEntry(
            id=entry_id,
            title=title,
            content=content,
            category=category,
            importance=max(1, min(10, importance)),
            priority=priority,
            tags=tags or [],
            source=source,
            is_permanente=is_permanente,
        )

        row = self._entry_to_row(entry)
        row["created_at"] = now
        row["last_accessed"] = now
        self._db.insert_memory(row)

        self._emit(EVENT_MEMORY_CREATED, {
            "id": entry_id,
            "title": title,
            "category": category.value,
            "importance": entry.importance,
        })

        self._logger.info(f"Memória salva: [{entry_id}] {title}")
        return entry

    def get(self, memory_id: str) -> MemoryEntry | None:
        """Recupera uma memória pelo ID."""
        row = self._db.get_memory(memory_id)
        if not row:
            return None

        # Atualizar access_count e last_accessed
        now = datetime.now().isoformat()
        new_count = row.get("access_count", 0) + 1
        self._db.update_memory(
            memory_id, last_accessed=now, access_count=new_count
        )

        row["last_accessed"] = now
        row["access_count"] = new_count

        self._emit(EVENT_MEMORY_RETRIEVED, {
            "id": memory_id,
            "title": row.get("title", ""),
        })

        return self._row_to_entry(row)

    def search(
        self,
        query: str = "",
        category: MemoryCategory | None = None,
        min_importance: int = 0,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Busca memórias por critérios."""
        cat_value = category.value if category else None
        rows = self._db.search_memories(
            query=query,
            category=cat_value,
            min_importance=min_importance,
            tags=tags,
            limit=limit,
        )
        return [self._row_to_entry(r) for r in rows]

    def delete(self, memory_id: str, confirm: bool = False) -> bool:
        """Remove uma memória."""
        row = self._db.get_memory(memory_id)
        if not row:
            return False

        is_perm = bool(row.get("is_permanente"))
        if is_perm and not confirm:
            self._logger.warning(
                f"Tentativa de apagar memória permanente [{memory_id}]: {row['title']}. "
                "Requer confirmação."
            )
            return False

        # Backup antes de apagar
        backup_dir = self._memory_dir / "Backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{memory_id}_backup.json"
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(row, f, ensure_ascii=False, indent=2)

        self._db.delete_memory(memory_id)

        self._emit(EVENT_MEMORY_DELETED, {
            "id": memory_id,
            "title": row["title"],
        })

        self._logger.info(f"Memória removida: [{memory_id}] {row['title']} (backup criado)")
        return True

    def update(self, memory_id: str, **kwargs) -> MemoryEntry | None:
        """Atualiza uma memória existente."""
        row = self._db.get_memory(memory_id)
        if not row:
            return None

        # Converter tags para JSON se fornecido
        if "tags" in kwargs and isinstance(kwargs["tags"], list):
            kwargs["tags"] = json.dumps(kwargs["tags"], ensure_ascii=False)
        if "category" in kwargs and hasattr(kwargs["category"], "value"):
            kwargs["category"] = kwargs["category"].value
        if "priority" in kwargs and hasattr(kwargs["priority"], "value"):
            kwargs["priority"] = kwargs["priority"].value

        self._db.update_memory(memory_id, **kwargs)
        updated = self._db.get_memory(memory_id)

        self._emit(EVENT_MEMORY_UPDATED, {
            "id": memory_id,
            "title": row["title"],
            "fields": list(kwargs.keys()),
        })

        self._logger.info(f"Memória atualizada: [{memory_id}] {row['title']}")
        return self._row_to_entry(updated) if updated else None

    def get_stats(self) -> dict:
        """Retorna estatísticas da memória."""
        db_stats = self._db.stats()

        # Espaço em disco (apenas diretório de backups legado)
        disk_usage = 0
        if self._memory_dir.exists():
            for file in self._memory_dir.rglob("*"):
                if file.is_file():
                    disk_usage += file.stat().st_size

        free_space = 0
        try:
            _disk_total, _disk_used, _disk_free = shutil.disk_usage(str(self._memory_dir))
            free_space = _disk_free
        except Exception:
            pass

        total = db_stats["total_memories"]
        categories = db_stats.get("by_category", {})

        # Média de importância
        all_rows = self._db.get_all_memories()
        avg_imp = 0.0
        if all_rows:
            avg_imp = round(
                sum(r.get("importance", 5) for r in all_rows) / len(all_rows), 2
            )

        return {
            "total_memories": total,
            "by_category": categories,
            "avg_importance": avg_imp,
            "disk_usage_bytes": disk_usage,
            "disk_usage_mb": round(disk_usage / (1024 * 1024), 2),
            "free_space_mb": round(free_space / (1024 * 1024), 2),
        }

    def should_save(self, text: str) -> bool:
        """Decide se uma informação deve ser salva como memória."""
        text_lower = text.lower().strip()

        skip_patterns = [
            "bom dia", "boa tarde", "boa noite",
            "obrigado", "obrigada", "valeu",
            "tchau", "até mais", "bye",
            "ok", "entendido", "certo",
        ]
        for pattern in skip_patterns:
            if text_lower == pattern:
                return False

        if len(text.split()) < 4:
            return False

        save_keywords = [
            "projeto", "sistema", "configuração", "preferência",
            "dispositivo", "automação", "rota", "diretório",
            "importante", "lembrar", "anotar", "salvar",
            "meu", "minha", "nosso", "nossa",
            "gosto", "gostei", "prefiro", "adoro", "odeio", "quero",
            "uso", "trabalho", "moro", "estudo",
            "esp32", "arduino", "python", "código",
        ]
        for keyword in save_keywords:
            if keyword in text_lower:
                return True

        if len(text.split()) >= 6:
            return True

        return False
