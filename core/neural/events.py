"""Modelo de eventos do A.R.I.S.

Todo evento estruturado que trafega pelo Event Bus possui, no mínimo:
``event_id``, ``event_type``, ``timestamp``, ``source``, ``payload``,
``confidence`` e ``priority``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Tipos de evento canônicos do sistema
EVENT_USER_MESSAGE = "user_message"
EVENT_VOICE_COMMAND = "voice_command"
EVENT_SCREEN_CHANGED = "screen_changed"
EVENT_TIMER_FINISHED = "timer_finished"
EVENT_SYSTEM_ALERT = "system_alert"
EVENT_HARDWARE = "hardware_event"
EVENT_INTENT = "intent"
EVENT_ACTION_RESULT = "action_result"
EVENT_ACTION_COMPLETED = "action_completed"
EVENT_GOAL_SET = "goal_set"
EVENT_DECISION_APPROVED = "decision_approved"
EVENT_BOOT = "system_boot"
EVENT_SHUTDOWN = "system_shutdown"
EVENT_INTERNAL = "internal"

# Tipos de evento da camada de percepção (sensores reais do mundo)
EVENT_PERCEPTION = "perception.event"
EVENT_CAMERA = "perception.camera"
EVENT_MICROPHONE = "perception.microphone"
EVENT_FILESYSTEM = "perception.filesystem"
EVENT_NETWORK = "perception.network"
EVENT_SYSTEM_METRIC = "perception.system_metric"

# Tipos de evento da camada de visão computacional (Vision Engine)
EVENT_VISION_SCREEN_ANALYZED = "vision.screen_analyzed"
EVENT_VISION_TEXT_DETECTED = "vision.text_detected"
EVENT_VISION_ERROR_DETECTED = "vision.error_detected"
EVENT_VISION_APPLICATION_DETECTED = "vision.application_detected"
EVENT_VISION_OBJECT_DETECTED = "vision.object_detected"

# Tipos de evento do sistema de memória (MemoryManager / KnowledgeGraph)
EVENT_MEMORY_CREATED = "memory.created"
EVENT_MEMORY_RETRIEVED = "memory.retrieved"
EVENT_MEMORY_UPDATED = "memory.updated"
EVENT_MEMORY_DELETED = "memory.deleted"

# Prioridades semânticas (0 = baixa, 100 = altíssima)
PRIORITY_LOW = 0
PRIORITY_NORMAL = 50
PRIORITY_HIGH = 75
PRIORITY_CRITICAL = 100

# Eventos produzidos pela camada de percepção (filtro de origem).
PERCEPTION_EVENT_TYPES = frozenset({
    EVENT_PERCEPTION,
    EVENT_CAMERA,
    EVENT_MICROPHONE,
    EVENT_SCREEN_CHANGED,
    EVENT_FILESYSTEM,
    EVENT_NETWORK,
    EVENT_SYSTEM_METRIC,
    EVENT_HARDWARE,
    EVENT_VISION_SCREEN_ANALYZED,
    EVENT_VISION_TEXT_DETECTED,
    EVENT_VISION_ERROR_DETECTED,
    EVENT_VISION_APPLICATION_DETECTED,
    EVENT_VISION_OBJECT_DETECTED,
})

# Eventos produzidos pelo sistema de memória.
MEMORY_EVENT_TYPES = frozenset({
    EVENT_MEMORY_CREATED,
    EVENT_MEMORY_RETRIEVED,
    EVENT_MEMORY_UPDATED,
    EVENT_MEMORY_DELETED,
})


@dataclass
class Event:
    """Evento estruturado do sistema.

    Attributes:
        event_type: Categoria do evento (ex.: ``user_message``).
        source: Identificação de quem produziu o evento.
        payload: Dados associados.
        confidence: Grau de certeza (0.0 a 1.0) da fonte.
        priority: Prioridade determinada pela fonte (0–100).
        event_id: Identificador único gerado automaticamente.
        timestamp: Momento da criação (ISO).
    """

    event_type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    priority: int = PRIORITY_NORMAL
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def text(self) -> str:
        """Forma textual do payload, para busca/contexto."""
        value = self.payload.get("text") or self.payload.get("query") or ""
        return str(value)

    def to_dict(self) -> dict[str, Any]:
        """Serializa o evento para dicionário."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "source": self.source,
            "payload": self.payload,
            "confidence": self.confidence,
            "priority": self.priority,
        }

    def __repr__(self) -> str:
        return (
            f"Event(type={self.event_type!r}, source={self.source!r}, "
            f"priority={self.priority}, confidence={self.confidence:.2f})"
        )
