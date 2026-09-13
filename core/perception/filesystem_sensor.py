"""Sensor de sistema de arquivos do A.R.I.S.

Vigia APENAS os diretórios explicitamente configurados (nada de varredura
global). Varre por polling a cada ``interval`` segundos e emite eventos
de criação, modificação e remoção de arquivos, com debounce por caminho.

Sem diretórios configurados, fica ``offline`` e emite zero eventos.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.neural.events import EVENT_FILESYSTEM, PRIORITY_NORMAL, Event
from core.perception.sensor import Sensor
from utils.logger import Logger

_MAX_ENTRIES = 5000


class FilesystemSensor(Sensor):
    """Sensor de mudanças em diretórios configurados."""

    name = "filesystem"

    def __init__(
        self,
        event_bus=None,
        enabled: bool = True,
        interval: float = 10.0,
        logger: Logger | None = None,
        watch_dirs: tuple[str, ...] = (),
        debounce: float = 30.0,
    ) -> None:
        super().__init__(event_bus=event_bus, enabled=enabled, interval=interval, logger=logger)
        self._watch_dirs: list[Path] = [Path(d) for d in watch_dirs if d]
        self._debounce = float(debounce)
        self._index: dict[str, tuple[float, int]] | None = None
        self._last_emit: dict[str, float] = {}

    @property
    def available(self) -> bool:
        return any(d.is_dir() for d in self._watch_dirs)

    def add_watch_dir(self, path: str | Path) -> None:
        """Espelha um diretório para observação."""
        p = Path(path)
        if p not in self._watch_dirs:
            self._watch_dirs.append(p)
            self._index = None

    def remove_watch_dir(self, path: str | Path) -> None:
        try:
            self._watch_dirs.remove(Path(path))
        except ValueError:
            pass

    # ── Varredura ────────────────────────────────────────────

    def _scan(self, root: Path) -> dict[str, tuple[float, int]]:
        result: dict[str, tuple[float, int]] = {}
        if not root.is_dir():
            return result
        pending = list(root.iterdir()) if root.exists() else []
        while pending and len(result) < _MAX_ENTRIES:
            entry = pending.pop(0)
            try:
                stat = entry.stat()
            except OSError:
                continue
            result[str(entry)] = (stat.st_mtime, stat.st_size)
            if entry.is_dir():
                try:
                    pending.extend(list(entry.iterdir()))
                except OSError:
                    continue
        return result

    def sense(self) -> list[Event]:
        if not self._enabled or not self._watch_dirs:
            return []
        current: dict[str, tuple[float, int]] = {}
        for root in self._watch_dirs:
            current.update(self._scan(root))
        if self._index is None:
            self._index = current
            return []

        events: list[Event] = []
        now = time.time()
        prev = self._index

        for path in sorted(set(current) - set(prev)):
            if self._debounced(path, "created", now):
                continue
            events.append(self._make_event(
                EVENT_FILESYSTEM,
                {"action": "created", "path": path,
                 "text": f"Novo arquivo: {path}"},
                priority=PRIORITY_NORMAL, confidence=0.9,
            ))
        for path in sorted(set(prev) - set(current)):
            if self._debounced(path, "removed", now):
                continue
            events.append(self._make_event(
                EVENT_FILESYSTEM,
                {"action": "removed", "path": path,
                 "text": f"Arquivo removido: {path}"},
                priority=PRIORITY_NORMAL, confidence=0.9,
            ))
        for path in sorted(set(current) & set(prev)):
            if current[path] == prev[path]:
                continue
            if self._debounced(path, "modified", now):
                continue
            events.append(self._make_event(
                EVENT_FILESYSTEM,
                {"action": "modified", "path": path,
                 "text": f"Arquivo modificado: {path}"},
                priority=PRIORITY_NORMAL, confidence=0.9,
            ))

        self._index = current
        return events

    def _debounced(self, path: str, action: str, now: float) -> bool:
        key = f"{action}:{path}"
        last = self._last_emit.get(key)
        if last is not None and now - last < self._debounce:
            return True
        self._last_emit[key] = now
        return False

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data.update({
            "watch_dirs": [str(d) for d in self._watch_dirs],
            "tracked_entries": len(self._index or {}),
        })
        return data
