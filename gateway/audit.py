"""Audit logging for CLL1 Gateway operations."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_audit_log: list[dict[str, Any]] = []
_MAX_ENTRIES = 1000


_REDACT_KEYS = ("groq_api_key", "api_key", "bot_token", "discord", "cll1_token",
                  "password", "secret", "passwd", "bearer")


def _redact(text: str) -> str:
    import re as _re
    t = text or ""
    # GROQ gsk_..., Discord tokens, Bearer
    t = _re.sub(r"gsk_[A-Za-z0-9_\-]{8,}", "gsk_***", t)
    t = _re.sub(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{8,}", r"\1***", t)
    t = _re.sub(r"(?i)(api[_-]?key\s*[:=]\s*['\"]?)[^'\"\s,}]{6,}", r"\1***", t)
    t = _re.sub(r"(?i)(token\s*[:=]\s*['\"]?)[^'\"\s,}]{6,}", r"\1***", t)
    return t[:200]


def log_operation(
    operation: str,
    *,
    user: str = "system",
    target: str = "",
    result: str = "ok",
    detail: str = "",
    duration_ms: float = 0,
) -> None:
    entry = {
        "ts": time.time(),
        "op": operation,
        "user": user,
        "target": _redact(target),
        "result": result,
        "detail": _redact(detail),
        "ms": round(duration_ms, 1),
    }
    _audit_log.append(entry)
    if len(_audit_log) > _MAX_ENTRIES:
        _audit_log.pop(0)


def get_recent(n: int = 50) -> list[dict[str, Any]]:
    return list(_audit_log[-n:])


def export_log(path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(_audit_log, f, indent=2, ensure_ascii=False)
