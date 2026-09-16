"""External Memory Manager — armazenamento persistente em dispositivo removivel.

Detecta pendrive automaticamente, cria estrutura de dados,
fornece fallback local quando pendrive nao esta disponivel.
"""
from __future__ import annotations

import os
import shutil
import string
import time
from datetime import datetime
from pathlib import Path


class ExternalMemoryManager:
    """Gerencia armazenamento persistente externo (pendrive)."""

    BASE_DIR = "ARIS"
    SUBDIRS = ["memory", "database", "backups", "files", "logs", "knowledge", "exports"]

    def __init__(self) -> None:
        self._drive: str | None = None
        self._base: Path | None = None
        self._fallback = Path.home() / ".aris" / "external"
        self._detect()

    def _detect(self) -> None:
        """Detecta dispositivo removivel automaticamente."""
        for letter in reversed(string.ascii_uppercase):
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                try:
                    vol = os.statdrive(drive)
                    if vol and vol[1] > 0 and vol[2] > 0:
                        if self._is_removable(drive):
                            self._drive = drive
                            self._base = Path(drive) / self.BASE_DIR
                            self._setup_dirs()
                            return
                except Exception:
                    continue

        self._base = self._fallback
        self._setup_dirs()

    def _is_removable(self, drive: str) -> bool:
        """Verifica se o drive e removivel."""
        try:
            import ctypes
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
            return drive_type == 2
        except Exception:
            return False

    def _setup_dirs(self) -> None:
        """Cria estrutura de diretorios."""
        if self._base:
            for sub in self.SUBDIRS:
                (self._base / sub).mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return self._base is not None

    @property
    def drive(self) -> str | None:
        return self._drive

    @property
    def base_path(self) -> Path:
        return self._base or self._fallback

    @property
    def is_external(self) -> bool:
        return self._drive is not None

    def get_path(self, subdir: str = "memory") -> Path:
        """Retorna caminho para subdiretorio."""
        path = self.base_path / subdir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def store(self, category: str, key: str, data: str) -> dict:
        """Armazena dado persistente."""
        try:
            subdir = "memory" if category in ("profile", "preferences", "facts") else category
            path = self.get_path(subdir)
            file_path = path / f"{key}.txt"
            file_path.write_text(data, encoding="utf-8")
            return {"ok": True, "path": str(file_path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def retrieve(self, category: str, key: str) -> str | None:
        """Recupera dado persistente."""
        try:
            path = self.get_path(category)
            file_path = path / f"{key}.txt"
            if file_path.exists():
                return file_path.read_text(encoding="utf-8")
            return None
        except Exception:
            return None

    def search(self, query: str) -> list[dict]:
        """Busca em todos os dados persistentes."""
        results = []
        query_lower = query.lower()
        for subdir in self.SUBDIRS:
            path = self.get_path(subdir)
            for f in path.glob("*.txt"):
                try:
                    content = f.read_text(encoding="utf-8")
                    if query_lower in content.lower():
                        results.append({
                            "file": f.name,
                            "category": subdir,
                            "preview": content[:200],
                        })
                except Exception:
                    continue
        return results

    def backup(self) -> dict:
        """Cria backup dos dados."""
        if not self.is_external:
            return {"ok": False, "error": "Sem pendrive para backup."}
        try:
            backup_dir = self.get_path("backups")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_{timestamp}"
            backup_path = backup_dir / backup_name
            shutil.copytree(self.get_path("memory"), backup_path, dirs_exist_ok=True)
            return {"ok": True, "path": str(backup_path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync_from_fallback(self) -> dict:
        """Sincroniza dados do fallback local para o pendrive."""
        if not self.is_external:
            return {"ok": False, "error": "Pendrive nao disponivel."}
        if not self._fallback.exists():
            return {"ok": True, "message": "Nada para sincronizar."}
        try:
            for subdir in self.SUBDIRS:
                src = self._fallback / subdir
                dst = self.get_path(subdir)
                if src.exists():
                    for f in src.glob("*"):
                        if f.is_file():
                            dst_file = dst / f.name
                            if not dst_file.exists():
                                shutil.copy2(f, dst_file)
            return {"ok": True, "message": "Sincronizado do fallback."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_status(self) -> dict:
        """Status do armazenamento externo."""
        return {
            "available": self.available,
            "drive": self.drive,
            "is_external": self.is_external,
            "base_path": str(self.base_path),
            "subdirs": {
                sub: len(list(self.get_path(sub).glob("*")))
                for sub in self.SUBDIRS
            },
        }


_instance: ExternalMemoryManager | None = None


def get_external_memory() -> ExternalMemoryManager:
    global _instance
    if _instance is None:
        _instance = ExternalMemoryManager()
    return _instance
