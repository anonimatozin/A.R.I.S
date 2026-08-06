"""Organizador de memória do J.A.R.V.I.S.

Responsável pela limpeza automática, organização e manutenção
do sistema de memória.
"""

import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from core.memory import MemoryManager
from core.memory_models import MemoryEntry, MemoryCategory
from utils.logger import Logger


class MemoryOrganizer:
    """Organizador automático de memórias.

    Gerencia limpeza, backup, compactação e reorganização
    do sistema de memória.
    """

    def __init__(self, memory_manager: MemoryManager, logger: Logger) -> None:
        """Inicializa o organizador.

        Args:
            memory_manager: Instância do gerenciador de memória.
            logger: Instância do logger.
        """
        self._memory = memory_manager
        self._logger = logger
        self._memory_dir = memory_manager._memory_dir

    def run_maintenance(self) -> dict:
        """Executa rotina completa de manutenção.

        Returns:
            Dicionário com resultado da manutenção.
        """
        self._logger.info("Iniciando rotina de manutenção da memória...")

        result = {
            "cache_cleaned": self.clean_cache(),
            "temp_cleaned": self.clean_temporary(),
            "logs_archived": self.archive_old_logs(),
            "backups_compacted": self.compact_old_backups(),
            "duplicates_removed": self.remove_duplicates(),
            "stale_archived": self.archive_stale_memories(),
            "integrity_ok": self.verify_integrity(),
        }

        self._logger.info("Rotina de manutenção concluída.")
        return result

    def clean_cache(self) -> int:
        """Limpa arquivos do cache.

        Returns:
            Quantidade de arquivos removidos.
        """
        cache_dir = self._memory_dir / "Cache"
        if not cache_dir.exists():
            return 0

        count = 0
        for file in cache_dir.glob("*"):
            if file.is_file():
                try:
                    file.unlink()
                    count += 1
                except Exception as e:
                    self._logger.error(f"Erro ao remover cache: {e}")

        self._logger.info(f"Cache limpo: {count} arquivos removidos.")
        return count

    def clean_temporary(self) -> int:
        """Limpa arquivos temporários.

        Returns:
            Quantidade de arquivos removidos.
        """
        temp_dir = self._memory_dir / "Temporary"
        if not temp_dir.exists():
            return 0

        count = 0
        for file in temp_dir.glob("*"):
            if file.is_file():
                # Remover arquivos com mais de 7 dias
                try:
                    mtime = datetime.fromtimestamp(file.stat().st_mtime)
                    if datetime.now() - mtime > timedelta(days=7):
                        file.unlink()
                        count += 1
                except Exception as e:
                    self._logger.error(f"Erro ao remover temporário: {e}")

        self._logger.info(f"Temporários limpos: {count} arquivos removidos.")
        return count

    def archive_old_logs(self) -> int:
        """Move logs antigos para Archive.

        Returns:
            Quantidade de arquivos arquivados.
        """
        logs_dir = self._memory_dir / "Logs"
        archive_dir = self._memory_dir / "Archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        if not logs_dir.exists():
            return 0

        count = 0
        for file in logs_dir.glob("*.log*"):
            if file.is_file():
                try:
                    mtime = datetime.fromtimestamp(file.stat().st_mtime)
                    if datetime.now() - mtime > timedelta(days=30):
                        dest = archive_dir / f"logs_{file.name}"
                        shutil.move(str(file), str(dest))
                        count += 1
                except Exception as e:
                    self._logger.error(f"Erro ao arquivar log: {e}")

        self._logger.info(f"Logs arquivados: {count} arquivos.")
        return count

    def compact_old_backups(self) -> int:
        """Remove backups antigos (mantém apenas os 10 mais recentes).

        Returns:
            Quantidade de backups removidos.
        """
        backups_dir = self._memory_dir / "Backups"
        if not backups_dir.exists():
            return 0

        backups = sorted(
            backups_dir.glob("*_backup.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        count = 0
        for backup in backups[10:]:
            try:
                backup.unlink()
                count += 1
            except Exception as e:
                self._logger.error(f"Erro ao remover backup: {e}")

        if count > 0:
            self._logger.info(f"Backups compactados: {count} antigos removidos.")
        return count

    def remove_duplicates(self) -> int:
        """Remove memórias duplicadas (mesmo conteúdo).

        Returns:
            Quantidade de duplicatas removidas.
        """
        seen_contents: dict[str, str] = {}
        to_remove: list[str] = []

        for entry in self._memory._memories.values():
            content_hash = hash(entry.content.strip().lower())
            if content_hash in seen_contents:
                # Manter a mais importante
                existing = self._memory._memories.get(seen_contents[content_hash])
                if existing and entry.importance < existing.importance:
                    to_remove.append(entry.id)
                elif existing:
                    to_remove.append(seen_contents[content_hash])
                    seen_contents[content_hash] = entry.id
            else:
                seen_contents[content_hash] = entry.id

        count = 0
        for mem_id in to_remove:
            if self._memory.delete(mem_id, confirm=True):
                count += 1

        if count > 0:
            self._logger.info(f"Duplicatas removidas: {count}")
        return count

    def archive_stale_memories(self) -> int:
        """Arquiva memórias obsoletas.

        Returns:
            Quantidade de memórias arquivadas.
        """
        archive_dir = self._memory_dir / "Archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for entry in list(self._memory._memories.values()):
            if entry.is_stale and entry.category != MemoryCategory.ARCHIVE:
                entry.category = MemoryCategory.ARCHIVE
                self._memory._save_to_disk(entry)
                count += 1

        if count > 0:
            self._memory._save_index()
            self._logger.info(f"Memórias obsoletas arquivadas: {count}")
        return count

    def verify_integrity(self) -> bool:
        """Verifica integridade do índice.

        Returns:
            True se íntegro.
        """
        try:
            # Verificar se todos os arquivos no índice existem no disco
            corrupted = 0
            for entry in list(self._memory._memories.values()):
                if entry.file_path:
                    if not Path(entry.file_path).exists():
                        self._memory._memories.pop(entry.id, None)
                        corrupted += 1

            if corrupted > 0:
                self._memory._save_index()
                self._logger.warning(f"Integridade: {corrupted} entradas órfãs removidas.")
            else:
                self._logger.info("Integridade: OK")

            return True
        except Exception as e:
            self._logger.error(f"Erro na verificação de integridade: {e}")
            return False

    def get_disk_info(self) -> dict:
        """Retorna informações sobre o espaço em disco.

        Returns:
            Dicionário com informações de disco.
        """
        try:
            total, used, free = shutil.disk_usage(str(self._memory_dir))
            return {
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free / (1024**3), 2),
                "percent_used": round((used / total) * 100, 1),
            }
        except Exception as e:
            self._logger.error(f"Erro ao obter info de disco: {e}")
            return {}
