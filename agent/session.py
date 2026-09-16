"""Session Manager — gerencia sessao ativa do A.R.I.S.

Sessao ativa: 60 segundos sem interacao → volta pra idle.
Cada interacao reinicia o timer.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum


class SessionState(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    PROCESSING = "processing"


class SessionManager:
    """Gerencia sessao ativa com timeout de 60s."""

    DEFAULT_TIMEOUT = 60.0  # segundos

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._state = SessionState.IDLE
        self._last_interaction: float = 0.0
        self._session_start: float = 0.0
        self._interaction_count: int = 0
        self._on_state_change: Callable[[SessionState, SessionState], None] | None = None

    @property
    def state(self) -> SessionState:
        """Estado atual, verificando timeout."""
        if self._state == SessionState.ACTIVE:
            if time.time() - self._last_interaction > self._timeout:
                self._set_state(SessionState.IDLE)
        return self._state

    @property
    def is_active(self) -> bool:
        return self.state == SessionState.ACTIVE

    @property
    def time_since_last_interaction(self) -> float:
        if self._last_interaction == 0:
            return 0.0
        return time.time() - self._last_interaction

    @property
    def time_until_idle(self) -> float:
        if self._state != SessionState.ACTIVE:
            return 0.0
        remaining = self._timeout - self.time_since_last_interaction
        return max(0.0, remaining)

    @property
    def interaction_count(self) -> int:
        return self._interaction_count

    @property
    def session_duration(self) -> float:
        if self._session_start == 0:
            return 0.0
        return time.time() - self._session_start

    def on_state_change(self, callback: Callable[[SessionState, SessionState], None]) -> None:
        self._on_state_change = callback

    def activate(self) -> bool:
        """Ativa a sessao (wake word ou interacao).

        Returns:
            True se a sessao foi ativada (era idle).
        """
        was_idle = self._state == SessionState.IDLE
        self._last_interaction = time.time()
        self._interaction_count += 1

        if was_idle:
            self._session_start = time.time()
            self._set_state(SessionState.ACTIVE)
            return True
        return False

    def touch(self) -> None:
        """Registra interacao (reinicia timer)."""
        self._last_interaction = time.time()
        if self._state == SessionState.IDLE:
            self.activate()

    def deactivate(self) -> None:
        """Desativa a sessao."""
        self._set_state(SessionState.IDLE)

    def set_processing(self, processing: bool = True) -> None:
        """Marca como processando (evita timeout durante execucao)."""
        if processing:
            self._set_state(SessionState.PROCESSING)
        else:
            if self._state == SessionState.PROCESSING:
                self._set_state(SessionState.ACTIVE)

    def check_timeout(self) -> bool:
        """Verifica se a sessao expirou.

        Returns:
            True se expirou (voltou pra idle).
        """
        if self._state in (SessionState.ACTIVE, SessionState.PROCESSING):
            if time.time() - self._last_interaction > self._timeout:
                self._set_state(SessionState.IDLE)
                return True
        return False

    def get_status(self) -> dict:
        """Status da sessao."""
        return {
            "state": self.state.value,
            "time_since_last": round(self.time_since_last_interaction, 1),
            "time_until_idle": round(self.time_until_idle, 1),
            "interactions": self._interaction_count,
            "duration": round(self.session_duration, 1),
            "timeout": self._timeout,
        }

    def _set_state(self, new_state: SessionState) -> None:
        old = self._state
        if old == new_state:
            return
        self._state = new_state
        if self._on_state_change:
            try:
                self._on_state_change(old, new_state)
            except Exception:
                pass
