"""Backup and restore operations."""

from __future__ import annotations

import os
import tarfile
import time
from typing import Any

BACKUP_DIR = "backups"


def create_backup(base_dir: str, name: str = "") -> dict[str, Any]:
    backup_dir = os.path.join(base_dir, BACKUP_DIR)
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = int(time.time())
    backup_name = name or f"backup_{timestamp}"
    backup_path = os.path.join(backup_dir, f"{backup_name}.tar.gz")

    include_dirs = ["cll1", "edge", "modules", "utils", "gateway"]
    include_files = [".env"]

    with tarfile.open(backup_path, "w:gz") as tar:
        for d in include_dirs:
            src = os.path.join(base_dir, d)
            if os.path.exists(src):
                tar.add(src, arcname=d)
        for f in include_files:
            src = os.path.join(base_dir, f)
            if os.path.exists(src):
                tar.add(src, arcname=f)

    size = os.path.getsize(backup_path)
    return {"ok": True, "name": backup_name, "path": backup_path, "size": size}


def list_backups(base_dir: str) -> list[dict[str, Any]]:
    backup_dir = os.path.join(base_dir, BACKUP_DIR)
    if not os.path.exists(backup_dir):
        return []
    backups = []
    for f in sorted(os.listdir(backup_dir)):
        if f.endswith(".tar.gz"):
            path = os.path.join(backup_dir, f)
            backups.append({
                "name": f.replace(".tar.gz", ""),
                "path": path,
                "size": os.path.getsize(path),
                "created": os.path.getmtime(path),
            })
    return backups


def restore_backup(base_dir: str, name: str) -> dict[str, Any]:
    backup_dir = os.path.join(base_dir, BACKUP_DIR)
    backup_path = os.path.join(backup_dir, f"{name}.tar.gz")
    if not os.path.exists(backup_path):
        return {"ok": False, "error": f"Backup {name} not found"}

    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(path=base_dir)
        return {"ok": True, "name": name, "restored": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def delete_backup(base_dir: str, name: str) -> dict[str, Any]:
    backup_dir = os.path.join(base_dir, BACKUP_DIR)
    backup_path = os.path.join(backup_dir, f"{name}.tar.gz")
    if not os.path.exists(backup_path):
        return {"ok": False, "error": f"Backup {name} not found"}
    os.remove(backup_path)
    return {"ok": True, "name": name, "deleted": True}
