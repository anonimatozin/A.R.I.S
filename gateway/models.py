"""Data models for the CLL1 Control Center."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Request:
    type: str
    token: str = ""
    args: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> Request:
        return cls(
            type=d.get("type", ""),
            token=d.get("token", ""),
            args={k: v for k, v in d.items() if k not in ("type", "token")},
        )


@dataclass
class Response:
    ok: bool
    operation: str = ""
    error: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = {"ok": self.ok}
        if self.operation:
            result["operation"] = self.operation
        if self.error:
            result["error"] = self.error
        result.update(self.data)
        return result

    @classmethod
    def success(cls, operation: str = "", **data) -> Response:
        return cls(ok=True, operation=operation, data=data)

    @classmethod
    def error_resp(cls, error: str, operation: str = "") -> Response:
        return cls(ok=False, error=error, operation=operation)


@dataclass
class AuditEntry:
    ts: float = field(default_factory=time.time)
    op: str = ""
    user: str = "system"
    target: str = ""
    result: str = "ok"
    detail: str = ""
    duration_ms: float = 0
