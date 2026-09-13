"""Ponte de atenção do A.R.I.S.

Interliga Percepção → Atenção → Estado → Memória conforme a arquitetura:

    sensor → EventBus → AttentionEngine → GlobalState → Memória episódica

Assina o barramento como observador (somente leitura). Cada evento é
pontuado pelo ``AttentionEngine``; apenas o que realmente merece atenção
(HIGH/CRITICAL) é registrado no estado global e na memória episódica.
Todo evento acompanhado vira registro do log de atenção (para responder
"o que chamou sua atenção?").
"""

from __future__ import annotations

from typing import Any

from core.neural.attention.attention_engine import AttentionEngine, AttentionLevel
from core.neural.event_bus import EventBus
from core.neural.events import (
    EVENT_GOAL_SET,
    EVENT_SYSTEM_ALERT,
    EVENT_TIMER_FINISHED,
    EVENT_USER_MESSAGE,
    EVENT_VOICE_COMMAND,
    PERCEPTION_EVENT_TYPES,
    Event,
)
from core.neural.memory.system import Experience
from core.neural.state import GlobalState
from utils.logger import Logger

# Tipos que alimentam o log de atenção (evita ruído interno).
_TRACKED_TYPES = frozenset({
    *PERCEPTION_EVENT_TYPES,
    EVENT_USER_MESSAGE,
    EVENT_VOICE_COMMAND,
    EVENT_SYSTEM_ALERT,
    EVENT_TIMER_FINISHED,
    EVENT_GOAL_SET,
})


class AttentionBridge:
    """Observador do bus que decide o que merece atenção."""

    def __init__(
        self,
        event_bus: EventBus,
        attention: AttentionEngine,
        state: GlobalState | None = None,
        memory=None,
        logger: Logger | None = None,
        enabled: bool = True,
    ) -> None:
        self._bus = event_bus
        self._attention = attention
        self._state = state
        self._memory = memory
        self._logger = logger
        self._enabled = bool(enabled)
        self._seen = 0
        self._filtered = 0
        self._bus.subscribe("*", self._on_event)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def _on_event(self, event: Event) -> None:
        if not self._enabled or event.event_type not in _TRACKED_TYPES:
            return
        self._seen += 1
        user_intent = self._state.current_goal if self._state else None
        scored, level = self._attention.classify(event, user_intent)
        self._attention.observe(scored)

        if self._state is not None:
            self._state.update_perception(
                last_attention=level.value,
                attention_score=round(scored.score, 3),
                attention_focus=event.text[:60],
            )

        if level not in (AttentionLevel.HIGH, AttentionLevel.CRITICAL):
            self._filtered += 1
            return

        # Estado global e memória recebem somente estímulos de PERCEPÇÃO;
        # consultas/eventos do operador são tratados pelo próprio NeuralCore.
        if event.event_type not in PERCEPTION_EVENT_TYPES:
            self._filtered += 1
            return

        if self._state is not None:
            self._state.register_event(event)
        self._record_memory(event, scored.score, level)

    def _record_memory(self, event: Event, importance: float, level: AttentionLevel) -> None:
        if self._memory is None:
            return
        try:
            episodic = getattr(self._memory, "episodic", None)
            if episodic is None or not hasattr(episodic, "record"):
                return
            episodic.record(Experience(
                event=f"[percepção/{level.value}] {event.text or event.event_type}",
                context={"source": event.source, "priority": event.priority},
                importance=min(1.0, importance),
            ))
        except Exception as e:
            if self._logger:
                self._logger.warning(f"AttentionBridge: memória ({e})")

    def get_stats(self) -> dict[str, Any]:
        return {
            "seen": self._seen,
            "filtered": self._filtered,
            "enabled": self._enabled,
            "recent": self._attention.recent_attention(10),
        }
