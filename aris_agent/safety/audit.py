"""Auditoria JSONL das chamadas de ferramenta (com rotação por tamanho).

Nunca grava conteúdo de arquivos nem chaves: só metadados redigidos e um
resumo curto (status + tamanho); a pré-visualização de saída é opcional.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("aris.agent.safety.audit")


class AuditLogger:
    """Grava um evento JSON por linha em ``path``, girando o arquivo pelo tamanho."""

    def __init__(self, path: Path | str | None, *, max_bytes: int = 2_000_000) -> None:
        self.path = Path(path) if path else None
        self.max_bytes = max(100, int(max_bytes))
        self._warned = False

    def record(self, event: dict) -> None:
        """Grava ``event``; falhas de disco só geram aviso (nunca derrubam o laço)."""
        if self.path is None:
            return
        try:
            payload = {"ts": round(time.time(), 3), **event}
            line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
            self._rotate(len(line))
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except (OSError, TypeError, ValueError) as exc:
            if not self._warned:
                self._warned = True
                log.warning("não consegui gravar auditoria em %s: %s", self.path, exc)

    def _rotate(self, incoming: int) -> None:
        """Gira ``audit.jsonl`` -> ``audit.jsonl.1`` quando passar do limite."""
        if self.path is None:
            return
        try:
            if self.path.exists() and self.path.stat().st_size + incoming > self.max_bytes:
                backup = Path(str(self.path) + ".1")
                os.replace(self.path, backup)
                log.info("auditoria rotacionada para %s", backup)
        except OSError as exc:
            log.warning("rotação da auditoria falhou: %s", exc)

    def read_all(self) -> list[dict]:
        """Lê os eventos do arquivo atual (testes/depuração)."""
        if self.path is None or not self.path.exists():
            return []
        events: list[dict] = []
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:  # pragma: no cover - defensivo
                    log.warning("linha inválida na auditoria: %.80s", line)
        return events
