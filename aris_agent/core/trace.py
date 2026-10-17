"""Trace JSONL por tarefa em ``data_dir/traces/`` (a Parte 9 lê para visualizar)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ..contract.utils import redact_secrets, truncate_text

log = logging.getLogger("aris.agent.core.trace")

_LIMITE_CAMPO = 1500


def _limpar(value: object) -> object:
    """Redige segredos e trunca strings de um valor JSON-friendly."""
    if isinstance(value, str):
        return truncate_text(redact_secrets(value), _LIMITE_CAMPO)
    if isinstance(value, dict):
        return {key: _limpar(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_limpar(item) for item in value]
    return value


class TraceWriter:
    """Append de eventos JSONL de uma tarefa; falha de disco nunca derruba o laço."""

    def __init__(self, pasta: Path, trace_id: str) -> None:
        self.trace_id = trace_id
        self.path = Path(pasta) / f"{trace_id}.jsonl"
        self._fh = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a", encoding="utf-8")
        except OSError as exc:
            log.warning("nao consegui abrir o trace %s: %s", self.path, exc)

    def write(self, evento: str, **campos: object) -> None:
        """Escreve uma linha; ``evento`` é o tipo e o resto vira campos do registro."""
        if self._fh is None:
            return
        registro = {"evento": evento, "ts": round(time.time(), 3)}
        registro.update({key: _limpar(value) for key, value in campos.items()})
        try:
            self._fh.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
        except OSError as exc:
            log.warning("falha ao gravar trace %s: %s", self.path, exc)
            self.close()

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:  # pragma: no cover - defensivo
                pass
            self._fh = None


__all__ = ["TraceWriter"]
