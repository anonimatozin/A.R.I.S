"""System metrics and monitoring."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any


def get_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "timestamp": time.time(),
        "uptime": _get_uptime(),
        "cpu": _get_cpu(),
        "memory": _get_memory(),
        "disk": _get_disk(),
        "processes": _get_process_count(),
    }
    return metrics


def _get_uptime() -> str:
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h {mins}m"
    except Exception:
        return "unknown"


def _get_cpu() -> dict[str, Any]:
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        idle = int(parts[4])
        total = sum(int(x) for x in parts[1:])
        return {"idle": idle, "total": total, "percent": round(100 * (1 - idle / max(total, 1)), 1)}
    except Exception:
        return {"percent": 0}


def _get_memory() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["free", "-m"], capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
        parts = lines[1].split()
        total = int(parts[1])
        used = int(parts[2])
        return {"total_mb": total, "used_mb": used, "percent": round(100 * used / max(total, 1), 1)}
    except Exception:
        return {"total_mb": 0, "used_mb": 0, "percent": 0}


def _get_disk() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["df", "-m", "/"], capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
        parts = lines[1].split()
        total = int(parts[1])
        used = int(parts[2])
        return {"total_mb": total, "used_mb": used, "percent": round(100 * used / max(total, 1), 1)}
    except Exception:
        return {"total_mb": 0, "used_mb": 0, "percent": 0}


def _get_process_count() -> int:
    try:
        return len(os.listdir("/proc"))
    except Exception:
        return 0
