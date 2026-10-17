"""Circuit breaker por provedor: falhas seguidas tiram o provedor de cena."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("aris.agent.llm.circuit")


@dataclass
class _State:
    failures: int = 0
    open_until: float | None = None  # None = fechado
    probing: bool = False  # True = uma tentativa de prova foi liberada


class CircuitBreaker:
    """Fica ``open`` após ``failure_threshold`` falhas seguidas (ou auth).

    Depois do ``cooldown_s`` libera **uma** tentativa de prova (half-open):
    sucesso fecha, falha reabre. Relógio injetável.
    """

    def __init__(self, *, clock=None, failure_threshold: int = 3, cooldown_s: float = 60.0) -> None:
        self._clock = clock or time.monotonic
        self._failure_threshold = max(1, int(failure_threshold))
        self._cooldown_s = max(0.0, float(cooldown_s))
        self._lock = threading.Lock()
        self._states: dict[str, _State] = {}

    def _state(self, name: str) -> _State:
        state = self._states.get(name)
        if state is None:
            state = _State()
            self._states[name] = state
        return state

    def state(self, name: str) -> str:
        """``"closed"`` | ``"open"`` | ``"half_open"`` (sem efeito colateral)."""
        with self._lock:
            return self._state_unlocked(name)

    def _state_unlocked(self, name: str) -> str:
        state = self._state(name)
        if state.open_until is None:
            return "closed"
        if self._clock() >= state.open_until:
            return "half_open"
        return "open"

    def allow(self, name: str) -> bool:
        """Pode tentar agora? Libera no máximo uma prova por janela."""
        with self._lock:
            state = self._state(name)
            if state.open_until is None:
                return True
            if self._clock() < state.open_until:
                return False
            if state.probing:
                return False
            state.probing = True
            log.debug("circuit breaker de %r liberou tentativa de prova", name)
            return True

    def success(self, name: str) -> None:
        with self._lock:
            self._states[name] = _State()

    def failure(self, name: str, *, cooldown_s: float | None = None, immediate: bool = False) -> None:
        """Registra falha; abre o circuito no limite ou em falha imediata (auth)."""
        with self._lock:
            state = self._state(name)
            state.failures += 1
            if immediate or state.probing or state.failures >= self._failure_threshold:
                cooldown = self._cooldown_s if cooldown_s is None else max(0.0, float(cooldown_s))
                state.open_until = self._clock() + cooldown
                state.probing = False
                log.warning(
                    "circuit breaker de %r ABRIU por %.1fs (falha #%d%s)",
                    name,
                    cooldown,
                    state.failures,
                    ", auth" if immediate else "",
                )

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {name: self._state_unlocked(name) for name in sorted(self._states)}
