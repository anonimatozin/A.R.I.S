"""Controlled terminal/command execution."""

from __future__ import annotations

import subprocess
import time
from typing import Any

from gateway.security import CommandInjectionError, validate_command

DEFAULT_TIMEOUT = 30
MAX_OUTPUT = 100_000
DEFAULT_ALLOWLIST = [
    "ls", "cat", "head", "tail", "wc", "grep", "find", "df", "du",
    "ps", "top", "uptime", "date", "echo", "pwd", "whoami", "id",
    "which", "file", "stat", "sv", "ping",
]
# Removidos do allowlist: env/printenv (vazam segredos do processo).


def run_command(
    command: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    allowlist: list[str] | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    try:
        validated = validate_command(command, allowlist or DEFAULT_ALLOWLIST)
    except CommandInjectionError as e:
        return {
            "ok": False,
            "error": str(e),
            "exit_code": -1,
            "duration_ms": 0,
        }

    try:
        import shlex as _shlex
        argv = _shlex.split(validated)
        if not argv:
            return {"ok": False, "error": "Empty command", "exit_code": -1, "duration_ms": 0}
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        elapsed = (time.time() - t0) * 1000
        stdout = result.stdout[:MAX_OUTPUT]
        stderr = result.stderr[:MAX_OUTPUT]
        return {
            "ok": result.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": result.returncode,
            "duration_ms": round(elapsed, 1),
        }
    except subprocess.TimeoutExpired:
        elapsed = (time.time() - t0) * 1000
        return {
            "ok": False,
            "error": f"Command timed out after {timeout}s",
            "exit_code": -1,
            "duration_ms": round(elapsed, 1),
        }
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return {
            "ok": False,
            "error": str(e),
            "exit_code": -1,
            "duration_ms": round(elapsed, 1),
        }
