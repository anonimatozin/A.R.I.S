"""Modelos da memória cognitiva."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _now() -> str:
    return datetime.now(UTC).isoformat()


class MemoryKind(StrEnum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    CONVERSATION = "conversation"


class StorageClass(StrEnum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"
    TEMPORARY = "temporary"


@dataclass
class MemoryItem:
    """Registro único de memória no banco SQLite."""

    id: str
    memory_type: MemoryKind
    content: str
    summary: str = ""
    storage_class: StorageClass = StorageClass.NORMAL
    importance: float = 5.0
    confidence: float = 0.7
    source: str = "system"
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    access_count: int = 0
    reinforcement_count: int = 0
    expiration: str | None = None
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_accessed: str = field(default_factory=_now)
    associations: list[Association] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        if not self.expiration:
            return False
        try:
            exp = datetime.fromisoformat(self.expiration)
            return datetime.now(UTC) > exp
        except ValueError:
            return False

    def to_row(self) -> tuple:
        return (
            self.id, self.memory_type.value, self.storage_class.value,
            self.content, self.summary, self.created_at, self.updated_at,
            self.last_accessed, self.importance, self.confidence, self.source,
            _json(self.tags), _json(self.entities), self.access_count,
            self.reinforcement_count, self.expiration, _json(self.metadata),
        )

    @classmethod
    def from_row(cls, row: tuple) -> MemoryItem:
        return cls(
            id=row[0],
            memory_type=MemoryKind(row[1]),
            storage_class=StorageClass(row[2]),
            content=row[3],
            summary=row[4],
            created_at=row[5],
            updated_at=row[6],
            last_accessed=row[7],
            importance=row[8],
            confidence=row[9],
            source=row[10],
            tags=_unjson(row[11]),
            entities=_unjson(row[12]),
            access_count=row[13],
            reinforcement_count=row[14],
            expiration=row[15],
            metadata=_unjson(row[16]),
        )


@dataclass
class Association:
    """Relação entre duas memórias."""

    memory_id: str
    related_memory_id: str
    relationship_type: str
    strength: float = 0.8
    notes: str = ""

    def to_row(self) -> tuple:
        return (self.memory_id, self.related_memory_id,
                self.relationship_type, self.strength, self.notes)


def _json(value: list | dict) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)


def _unjson(value: str | None) -> list:
    import json
    if not value:
        return []
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return []
