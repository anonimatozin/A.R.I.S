"""Service management operations."""

from __future__ import annotations

import os
import subprocess
from typing import Any


def sv_status(service: str = "cll1-main") -> dict[str, Any]:
    result = subprocess.run(
        ["sv", "status", service],
        capture_output=True, text=True, timeout=10,
    )
    return {
        "ok": True,
        "service": service,
        "output": result.stdout.strip() or result.stderr.strip(),
    }


def sv_restart(service: str = "cll1-main") -> dict[str, Any]:
    result = subprocess.run(
        ["sv", "restart", service],
        capture_output=True, text=True, timeout=10,
    )
    return {
        "ok": result.returncode == 0,
        "service": service,
        "output": result.stdout.strip() or result.stderr.strip(),
    }


def sv_stop(service: str = "cll1-main") -> dict[str, Any]:
    result = subprocess.run(
        ["sv", "stop", service],
        capture_output=True, text=True, timeout=10,
    )
    return {
        "ok": result.returncode == 0,
        "service": service,
        "output": result.stdout.strip() or result.stderr.strip(),
    }


def sv_enable(service: str = "cll1-main") -> dict[str, Any]:
    result = subprocess.run(
        ["sv-enable", service],
        capture_output=True, text=True, timeout=10,
    )
    return {
        "ok": result.returncode == 0,
        "service": service,
        "output": result.stdout.strip() or result.stderr.strip(),
    }


def read_log(log_path: str, lines: int = 50) -> dict[str, Any]:
    if not os.path.isfile(log_path):
        return {"ok": False, "error": f"Log not found: {log_path}"}
    with open(log_path, encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    return {
        "ok": True,
        "path": log_path,
        "lines": [line.rstrip() for line in all_lines[-lines:]],
        "total_lines": len(all_lines),
    }
