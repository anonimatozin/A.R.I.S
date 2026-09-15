"""MessageOrigin — metadados de proveniencia de cada mensagem.

Cada mensagem que entra no sistema A.R.I.S. carrega um MessageOrigin
que identifica de onde veio, permitindo logging, rate limiting e
decisoes de roteamento differenciadas.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MessageOrigin:
    """Metadados de proveniencia de uma mensagem.

    Attributes:
        source: Origem da mensagem ("discord" | "terminal" | "voice" | "cll1").
        channel: Identificador do canal (ex: "dm:123456", "tcp:8765").
        user_id: ID do usuario na fonte (ex: discord user ID, "local").
        session_id: ID da sessao de conversa (UUID por sessao).
        message_id: ID unico da mensagem (para deduplicacao).
        timestamp: Timestamp de criacao (time.time()).
    """

    source: str = "terminal"
    channel: str = "stdin"
    user_id: str = "local"
    session_id: str = ""
    message_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def with_source(self, source: str) -> MessageOrigin:
        """Retorna copia com source diferente (util para roteamento)."""
        return MessageOrigin(
            source=source,
            channel=self.channel,
            user_id=self.user_id,
            session_id=self.session_id,
            message_id=self.message_id,
            timestamp=self.timestamp,
        )

    def to_dict(self) -> dict[str, str | float]:
        """Serializa para dict (util para JSON)."""
        return {
            "source": self.source,
            "channel": self.channel,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | float]) -> MessageOrigin:
        """Deserializa de dict."""
        return cls(
            source=str(data.get("source", "unknown")),
            channel=str(data.get("channel", "")),
            user_id=str(data.get("user_id", "")),
            session_id=str(data.get("session_id", "")),
            message_id=str(data.get("message_id", "")),
            timestamp=float(data.get("timestamp", time.time())),
        )
