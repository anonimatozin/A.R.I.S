"""Contabilidade de tokens por provedor e por dia, em JSON com escrita atômica."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from ..contract.types import Usage
from .limits import day_key

log = logging.getLogger("aris.agent.llm.stats")


def _blank() -> dict:
    return {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}


def _bump(target: dict, usage: Usage) -> None:
    target["requests"] = int(target.get("requests", 0)) + 1
    target["prompt_tokens"] = int(target.get("prompt_tokens", 0)) + int(usage.prompt_tokens)
    target["completion_tokens"] = (
        int(target.get("completion_tokens", 0)) + int(usage.completion_tokens)
    )


class UsageStats:
    """Arquivo JSON ``{"providers": ..., "days": ...}`` com escrita atômica."""

    def __init__(self, path: Path | str, *, wall=None) -> None:
        self.path = Path(path)
        self._wall = wall or time.time
        self._lock = threading.Lock()
        self._data: dict = {"providers": {}, "days": {}}

    def load(self) -> None:
        """Lê o arquivo; ausente/corrompido gera apenas aviso (não é erro fatal)."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("não consegui ler %s: %s (começando do zero)", self.path, exc)
            return
        if not isinstance(raw, dict):
            log.warning("%s não é um objeto JSON; começando do zero", self.path)
            return
        providers = raw.get("providers")
        days = raw.get("days")
        with self._lock:
            self._data = {
                "providers": providers if isinstance(providers, dict) else {},
                "days": days if isinstance(days, dict) else {},
            }

    def record(self, provider: str, model: str, usage: Usage) -> None:
        """Soma o uso na memória (chame ``save()`` para persistir)."""
        with self._lock:
            providers = self._data.setdefault("providers", {})
            entry = providers.setdefault(provider, _blank())
            if not isinstance(entry, dict):
                entry = providers[provider] = _blank()
            _bump(entry, usage)
            models = entry.setdefault("models", {})
            model_entry = models.setdefault(model or "desconhecido", _blank())
            if isinstance(model_entry, dict):
                _bump(model_entry, usage)

            days = self._data.setdefault("days", {})
            day = days.setdefault(day_key(self._wall()), {})
            day_entry = day.setdefault(provider, _blank())
            if isinstance(day_entry, dict):
                _bump(day_entry, usage)

    def save(self) -> None:
        """Grava de forma atômica (arquivo temporário + ``os.replace``)."""
        with self._lock:
            payload = json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("não consegui gravar %s: %s", self.path, exc)

    def snapshot(self) -> dict:
        """Cópia dos dados (JSON-safe) para ``router.stats()``."""
        with self._lock:
            return json.loads(json.dumps(self._data, ensure_ascii=False))

    def day_tokens(self, provider: str, day: str | None = None) -> int:
        """Tokens (prompt+completion) usados por ``provider`` no dia indicado."""
        key = day or day_key(self._wall())
        with self._lock:
            entry = self._data.get("days", {}).get(key, {}).get(provider, {})
        if not isinstance(entry, dict):
            return 0
        return int(entry.get("prompt_tokens", 0)) + int(entry.get("completion_tokens", 0))
