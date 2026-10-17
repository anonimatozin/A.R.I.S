"""System metrics and monitoring — cross-platform via psutil."""

from __future__ import annotations

import time
from typing import Any

try:
    import psutil as _psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


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
    if HAS_PSUTIL:
        try:
            seconds = int(time.time() - _psutil.boot_time())
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            return f"{hours}h {mins}m"
        except Exception:
            pass
    return "unknown"


def _get_cpu() -> dict[str, Any]:
    if HAS_PSUTIL:
        try:
            percent = _psutil.cpu_percent(interval=0.1)
            return {"percent": round(percent, 1)}
        except Exception:
            pass
    return {"percent": 0}


def _get_memory() -> dict[str, Any]:
    if HAS_PSUTIL:
        try:
            mem = _psutil.virtual_memory()
            return {
                "total_mb": round(mem.total / (1024 * 1024)),
                "used_mb": round(mem.used / (1024 * 1024)),
                "percent": round(mem.percent, 1),
            }
        except Exception:
            pass
    return {"total_mb": 0, "used_mb": 0, "percent": 0}


def _get_disk() -> dict[str, Any]:
    if HAS_PSUTIL:
        try:
            import sys as _sys
            path = "C:\\" if _sys.platform == "win32" else "/"
            disk = _psutil.disk_usage(path)
            return {
                "total_mb": round(disk.total / (1024 * 1024)),
                "used_mb": round(disk.used / (1024 * 1024)),
                "percent": round(disk.percent, 1),
            }
        except Exception:
            pass
    return {"total_mb": 0, "used_mb": 0, "percent": 0}


def _get_process_count() -> int:
    if HAS_PSUTIL:
        try:
            return len(_psutil.pids())
        except Exception:
            pass
    return 0
