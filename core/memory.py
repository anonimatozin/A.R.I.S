"""Gerenciador de memória do A.R.I.S.

Sistema central de armazenamento, recuperação e busca de memórias.
"""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from core.memory_models import MemoryCategory, MemoryEntry, Priority
from utils.logger import Logger


class MemoryManager:
    """Gerenciador central do sistema de memória.

    Responsável por armazenar, recuperar, buscar e gerenciar
    todas as memórias do A.R.I.S.
    """

    INDEX_FILE = "memory_index.json"
    METADATA_DIR = "Index"

    def __init__(self, logger: Logger, memory_root: Path | None = None) -> None:
        """Inicializa o gerenciador de memória.

        Args:
            logger: Instância do logger.
            memory_root: Diretório raiz da memória.
        """
        self._logger = logger
        self._memories: dict[str, MemoryEntry] = {}
        self._memory_dir = memory_root or (Path(__file__).resolve().parent.parent / "data" / "memory")
        self._index_path = self._memory_dir / self.METADATA_DIR / self.INDEX_FILE

        self._setup_directories()
        self._load_index()
        # Persistência: garante que o índice exista desde o primeiro boot.
        # Assim ele não é reconstruído do zero nas execuções seguintes.
        if not self._index_path.exists():
            self._save_index()

    def _setup_directories(self) -> None:
        """Cria a estrutura de pastas da memória."""
        categories = [
            "Profile", "Knowledge", "Projects", "Conversations",
            "Devices", "Automations", "Plugins", "Config",
            "Cache", "Logs", "Temporary", "Backups", "Archive", "Index",
        ]

        created = False
        for category in categories:
            dir_path = self._memory_dir / category
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                created = True

        if created:
            self._logger.info(f"Estrutura de memória criada em: {self._memory_dir}")

    def _load_index(self) -> None:
        """Carrega o índice de memórias do disco."""
        if self._index_path.exists():
            try:
                with open(self._index_path, encoding="utf-8") as f:
                    data = json.load(f)
                for entry_data in data.get("memories", []):
                    entry = MemoryEntry.from_dict(entry_data)
                    self._memories[entry.id] = entry
                self._logger.info(f"Índice carregado: {len(self._memories)} memórias.")
            except Exception as e:
                self._logger.error(f"Erro ao carregar índice: {e}")
        else:
            self._logger.info("Nenhum índice encontrado. Criando novo.")

    def _save_index(self) -> None:
        """Salva o índice de memórias no disco."""
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "total_memories": len(self._memories),
                "memories": [m.to_dict() for m in self._memories.values()],
            }
            with open(self._index_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._logger.debug(f"Índice salvo: {len(self._memories)} memórias.")
        except Exception as e:
            self._logger.error(f"Erro ao salvar índice: {e}")

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
        """Salva uma nova memória.

        Args:
            title: Título da memória.
            content: Conteúdo da memória.
            category: Categoria.
            importance: Importância (1-10).
            priority: Prioridade.
            tags: Tags para indexação.
            source: Origem da informação.
            is_permanente: Se é permanente.

        Returns:
            A entrada de memória criada.
        """
        entry_id = str(uuid.uuid4())[:8]
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

        self._memories[entry_id] = entry
        self._save_to_disk(entry)
        self._save_index()

        self._logger.info(f"Memória salva: [{entry_id}] {title}")
        return entry

    def _save_to_disk(self, entry: MemoryEntry) -> None:
        """Salva uma memória no disco."""
        category_dir = self._memory_dir / entry.category.value
        category_dir.mkdir(parents=True, exist_ok=True)

        file_path = category_dir / f"{entry.id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(entry.to_json())

        entry.file_path = str(file_path)

    def get(self, memory_id: str) -> MemoryEntry | None:
        """Recupera uma memória pelo ID.

        Args:
            memory_id: ID da memória.

        Returns:
            A entrada de memória ou None.
        """
        entry = self._memories.get(memory_id)
        if entry:
            entry.access()
            self._save_index()
        return entry

    def search(
        self,
        query: str = "",
        category: MemoryCategory | None = None,
        min_importance: int = 0,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Busca memórias por critérios.

        Args:
            query: Texto para busca no título/conteúdo.
            category: Filtrar por categoria.
            min_importance: Importância mínima.
            tags: Filtrar por tags.
            limit: Limite de resultados.

        Returns:
            Lista de memórias encontradas.
        """
        results = list(self._memories.values())

        if query:
            query_lower = query.lower()
            results = [
                m for m in results
                if query_lower in m.title.lower()
                or query_lower in m.content.lower()
                or any(query_lower in tag.lower() for tag in m.tags)
            ]

        if category:
            results = [m for m in results if m.category == category]

        if min_importance > 0:
            results = [m for m in results if m.importance >= min_importance]

        if tags:
            results = [
                m for m in results
                if any(tag in m.tags for tag in tags)
            ]

        results.sort(key=lambda m: (m.importance, m.access_count), reverse=True)
        return results[:limit]

    def delete(self, memory_id: str, confirm: bool = False) -> bool:
        """Remove uma memória.

        Args:
            memory_id: ID da memória.
            confirm: Confirmação do operador.

        Returns:
            True se removida com sucesso.
        """
        entry = self._memories.get(memory_id)
        if not entry:
            return False

        if entry.is_permanente and not confirm:
            self._logger.warning(
                f"Tentativa de apagar memória permanente [{memory_id}]: {entry.title}. "
                "Requer confirmação."
            )
            return False

        # Criar backup antes de apagar
        backup_dir = self._memory_dir / "Backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{entry.id}_backup.json"
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(entry.to_json())

        # Remover do disco
        if entry.file_path and Path(entry.file_path).exists():
            Path(entry.file_path).unlink()

        # Remover do índice
        del self._memories[memory_id]
        self._save_index()

        self._logger.info(f"Memória removida: [{memory_id}] {entry.title} (backup criado)")
        return True

    def update(self, memory_id: str, **kwargs) -> MemoryEntry | None:
        """Atualiza uma memória existente.

        Args:
            memory_id: ID da memória.
            **kwargs: Campos a atualizar.

        Returns:
            A memória atualizada ou None.
        """
        entry = self._memories.get(memory_id)
        if not entry:
            return None

        for key, value in kwargs.items():
            if hasattr(entry, key):
                setattr(entry, key, value)

        self._save_to_disk(entry)
        self._save_index()

        self._logger.info(f"Memória atualizada: [{memory_id}] {entry.title}")
        return entry

    def get_stats(self) -> dict:
        """Retorna estatísticas da memória.

        Returns:
            Dicionário com estatísticas.
        """
        total = len(self._memories)
        categories = {}
        total_importance = 0

        for entry in self._memories.values():
            cat = entry.category.value
            categories[cat] = categories.get(cat, 0) + 1
            total_importance += entry.importance

        # Espaço em disco
        disk_usage = 0
        if self._memory_dir.exists():
            for file in self._memory_dir.rglob("*"):
                if file.is_file():
                    disk_usage += file.stat().st_size

        # Espaço livre
        free_space = 0
        try:
            _disk_total, _disk_used, _disk_free = shutil.disk_usage(str(self._memory_dir))
            free_space = _disk_free
        except Exception:
            pass

        return {
            "total_memories": total,
            "by_category": categories,
            "avg_importance": round(total_importance / total, 2) if total > 0 else 0,
            "disk_usage_bytes": disk_usage,
            "disk_usage_mb": round(disk_usage / (1024 * 1024), 2),
            "free_space_mb": round(free_space / (1024 * 1024), 2),
        }

    def should_save(self, text: str) -> bool:
        """Decide se uma informação deve ser salva como memória.

        Args:
            text: Texto para analisar.

        Returns:
            True se deve ser salvo.
        """
        text_lower = text.lower().strip()

        # Não salvar saudações e agradecimentos
        skip_patterns = [
            "bom dia", "boa tarde", "boa noite",
            "obrigado", "obrigada", "valeu",
            "tchau", "até mais", "bye",
            "ok", "entendido", "certo",
        ]
        for pattern in skip_patterns:
            if text_lower == pattern:
                return False

        # Não salvar frases muito curtas
        if len(text.split()) < 4:
            return False

        # Salvar se contiver informações relevantes
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

        # Salvar se for uma frase substantiva
        if len(text.split()) >= 6:
            return True

        return False
