"""Version tracking for A.R.I.S.

Provides commit hash + deploy timestamp for version verification.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


_VERSION_FILE = Path(__file__).resolve().parent.parent / "data" / "version.json"
_BOOT_TIME_FILE = Path(__file__).resolve().parent.parent / "data" / "gateway_boot.txt"


def _find_git_root() -> Path | None:
    """Find the git repository root by looking for .git directory."""
    current = Path(__file__).resolve().parent
    for _ in range(5):  # max 5 levels up
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def _get_git_commit() -> str:
    """Get current git commit hash (short)."""
    try:
        repo_root = _find_git_root()
        if repo_root is None:
            return "unknown"
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _get_git_dirty() -> bool:
    """Check if working tree has uncommitted changes."""
    try:
        repo_root = _find_git_root()
        if repo_root is None:
            return False
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _get_deploy_timestamp() -> float:
    """Get deploy timestamp from version file or boot time file."""
    try:
        if _VERSION_FILE.exists():
            with open(_VERSION_FILE, encoding="utf-8") as f:
                data = json.load(f)
                return float(data.get("deploy_timestamp", 0))
    except Exception:
        pass

    try:
        if _BOOT_TIME_FILE.exists():
            with open(_BOOT_TIME_FILE, encoding="utf-8") as f:
                return float(f.read().strip())
    except Exception:
        pass

    return time.time()


def _save_version_info() -> dict[str, Any]:
    """Save current version info to file."""
    info = {
        "commit": _get_git_commit(),
        "dirty": _get_git_dirty(),
        "deploy_timestamp": time.time(),
    }
    try:
        _VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump(info, f)
    except Exception:
        pass
    return info


def get_version_info() -> dict[str, Any]:
    """Get version information for /versao endpoint."""
    commit = _get_git_commit()
    deploy_ts = _get_deploy_timestamp()
    dirty = _get_git_dirty()

    return {
        "commit": commit,
        "dirty": dirty,
        "deploy_timestamp": deploy_ts,
        "deploy_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(deploy_ts)),
        "uptime_seconds": time.time() - deploy_ts,
    }


def format_version_text() -> str:
    """Format version info as human-readable text."""
    info = get_version_info()
    lines = [
        f"Versao: {info['commit']}",
        f"Deploy: {info['deploy_iso']}",
        f"Uptime: {int(info['uptime_seconds'])}s",
    ]
    if info["dirty"]:
        lines.append("AVISO: Working tree tem mudancas nao commitadas")
    return "\n".join(lines)


def initialize_version() -> dict[str, Any]:
    """Initialize version tracking on startup."""
    return _save_version_info()