"""Audit logging for CLL1 Gateway operations."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_audit_log: list[dict[str, Any]] = []
_MAX_ENTRIES = 1000


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
        "target": target,
        "result": result,
        "detail": detail[:200],
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
