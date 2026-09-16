"""Health checks for gateway and dependencies."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any


def run_health_checks(base_dir: str) -> dict[str, Any]:
    checks = {
        "timestamp": time.time(),
        "checks": {},
        "overall": "healthy",
    }

    checks["checks"]["service"] = _check_service()
    checks["checks"]["tcp_port"] = _check_port(8765)
    checks["checks"]["http_port"] = _check_port(8766)
    checks["checks"]["disk"] = _check_disk()
    checks["checks"]["memory"] = _check_memory()
    checks["checks"]["python"] = _check_python()
    checks["checks"]["env_file"] = _check_env_file(base_dir)
    checks["checks"]["log_dir"] = _check_log_dir(base_dir)

    failed = [k for k, v in checks["checks"].items() if not v.get("ok")]
    if failed:
        checks["overall"] = "degraded" if len(failed) < 3 else "unhealthy"
    checks["failed"] = failed

    return checks


def _check_service() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["sv", "status", "cll1-main"],
            capture_output=True, text=True, timeout=5
        )
        ok = result.returncode == 0 and "run:" in result.stdout
        return {"ok": ok, "detail": result.stdout.strip()}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


def _check_port(port: int) -> dict[str, Any]:
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        s.close()
        return {"ok": True, "detail": f"Port {port} listening"}
    except Exception:
        return {"ok": False, "detail": f"Port {port} not listening"}


def _check_disk() -> dict[str, Any]:
    try:
        stat = os.statvfs("/")
        total = (stat.f_blocks * stat.f_frsize) // (1024 * 1024)
        free = (stat.f_bavail * stat.f_frsize) // (1024 * 1024)
        used = total - free
        pct = round(100 * used / max(total, 1), 1)
        ok = pct < 90
        return {"ok": ok, "detail": f"{pct}% used ({used}MB/{total}MB)"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


def _check_memory() -> dict[str, Any]:
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        info = {}
        for line in lines:
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = int(parts[1].strip().split()[0])
                info[key] = val
        total = info.get("MemTotal", 0) // 1024
        avail = info.get("MemAvailable", info.get("MemFree", 0)) // 1024
        used = total - avail
        pct = round(100 * used / max(total, 1), 1)
        ok = pct < 90
        return {"ok": ok, "detail": f"{pct}% used ({used}MB/{total}MB)"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


def _check_python() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["python", "--version"], capture_output=True, text=True, timeout=5
        )
        return {"ok": result.returncode == 0, "detail": result.stdout.strip()}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


def _check_env_file(base_dir: str) -> dict[str, Any]:
    env_path = os.path.join(base_dir, ".env")
    ok = os.path.exists(env_path)
    return {"ok": ok, "detail": "Found" if ok else "Missing"}


def _check_log_dir(base_dir: str) -> dict[str, Any]:
    log_dir = os.path.join(base_dir, "logs")
    ok = os.path.isdir(log_dir)
    return {"ok": ok, "detail": "Found" if ok else "Missing"}
