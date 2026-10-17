"""Proteções de laço: limite de EXEC/DESTRUCTIVE por minuto e por tarefa,
e bloqueio da mesma chamada repetida seguidas vezes."""

from __future__ import annotations

import json
import threading
import time
from collections import deque

from ..contract.types import Risk


class LoopGuard:
    """Contador de chamadas por sessão + detecção de repetição em loop."""

    def __init__(
        self,
        *,
        repeat_limit: int = 3,
        per_minute: int = 10,
        per_task: int = 40,
    ) -> None:
        self.repeat_limit = max(2, int(repeat_limit))
        self.per_minute = max(1, int(per_minute))
        self.per_task = max(1, int(per_task))
        self._lock = threading.Lock()
        self._last_key: tuple[str, str] | None = None
        self._repeat = 0
        self._times: dict[str, deque[float]] = {}
        self._totals: dict[str, int] = {}

    @staticmethod
    def canonical(name: str, arguments: dict) -> str:
        """Chave canônica da chamada (nome + argumentos ordenados)."""
        try:
            payload = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):  # pragma: no cover - defensivo
            payload = repr(sorted((arguments or {}).items(), key=lambda kv: str(kv[0])))
        return f"{name}|{payload}"

    def check(self, key: str, risk: Risk, session_id: str) -> str | None:
        """Avalia e registra a chamada; devolve mensagem de erro ou ``None``.

        Regras: a 3ª chamada idêntica consecutiva é bloqueada; EXEC/DESTRUCTIVE
        respeitam ``per_minute`` (janela de 60 s) e ``per_task`` por sessão.
        """
        now = time.monotonic()
        with self._lock:
            if key == self._last_key:
                self._repeat += 1
            else:
                self._last_key = key
                self._repeat = 1
            if self._repeat >= self.repeat_limit:
                return (
                    f"a mesma chamada com os mesmos argumentos foi repetida "
                    f"{self._repeat} vezes seguidas; mude de estratégia: varie os "
                    "argumentos, use outra ferramenta ou pergunte ao usuário"
                )
            if risk >= Risk.EXEC:
                window = self._times.setdefault(session_id, deque())
                while window and now - window[0] > 60.0:
                    window.popleft()
                if len(window) >= self.per_minute:
                    return (
                        f"limite de {self.per_minute} comandos EXEC/DESTRUCTIVE por "
                        "minuto atingido nesta tarefa; espere ou faça menos chamadas"
                    )
                total = self._totals.get(session_id, 0)
                if total >= self.per_task:
                    return (
                        f"limite de {self.per_task} comandos EXEC/DESTRUCTIVE por "
                        "tarefa atingido; encerre o plano ou peça orientação ao usuário"
                    )
                window.append(now)
                self._totals[session_id] = total + 1
        return None

    def reset(self, session_id: str | None = None) -> None:
        """Zera contadores (uma sessão, ou tudo quando ``session_id`` é None)."""
        with self._lock:
            self._last_key = None
            self._repeat = 0
            if session_id is None:
                self._times.clear()
                self._totals.clear()
            else:
                self._times.pop(session_id, None)
                self._totals.pop(session_id, None)
