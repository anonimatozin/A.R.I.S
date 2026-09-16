"""Filesystem operations with sandbox protection."""

from __future__ import annotations

import base64
import os
import shutil

from gateway.security import safe_path

MAX_FILE_SIZE = 10 * 1024 * 1024


def list_files(base_dir: str, rel_path: str = ".") -> list[dict]:
    full = safe_path(rel_path, base_dir)
    if not os.path.isdir(full):
        return []
    entries = []
    for name in sorted(os.listdir(full)):
        fp = os.path.join(full, name)
        is_dir = os.path.isdir(fp)
        stat = os.stat(fp)
        rel = os.path.join(rel_path, name).replace("\\", "/")
        entries.append({
            "name": name,
            "path": rel,
            "is_dir": is_dir,
            "type": "dir" if is_dir else "file",
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })
    return entries


def read_file(base_dir: str, rel_path: str) -> str:
    full = safe_path(rel_path, base_dir)
    if not os.path.isfile(full):
        raise FileNotFoundError(f"File not found: {rel_path}")
    size = os.path.getsize(full)
    if size > MAX_FILE_SIZE:
        raise ValueError(f"File too large: {size} > {MAX_FILE_SIZE}")
    with open(full, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def write_file(base_dir: str, rel_path: str, content_b64: str) -> int:
    full = safe_path(rel_path, base_dir)
    data = base64.b64decode(content_b64)
    if len(data) > MAX_FILE_SIZE:
        raise ValueError(f"File too large: {len(data)} > {MAX_FILE_SIZE}")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(data)
    return len(data)


def delete_file(base_dir: str, rel_path: str) -> bool:
    full = safe_path(rel_path, base_dir)
    if os.path.isfile(full):
        os.remove(full)
        return True
    if os.path.isdir(full):
        shutil.rmtree(full)
        return True
    return False


def move_file(base_dir: str, src: str, dst: str) -> bool:
    src_full = safe_path(src, base_dir)
    dst_full = safe_path(dst, base_dir)
    if not os.path.exists(src_full):
        return False
    os.makedirs(os.path.dirname(dst_full), exist_ok=True)
    shutil.move(src_full, dst_full)
    return True


def copy_file(base_dir: str, src: str, dst: str) -> bool:
    src_full = safe_path(src, base_dir)
    dst_full = safe_path(dst, base_dir)
    if not os.path.exists(src_full):
        return False
    os.makedirs(os.path.dirname(dst_full), exist_ok=True)
    shutil.copy2(src_full, dst_full)
    return True


def mkdir(base_dir: str, rel_path: str) -> str:
    full = safe_path(rel_path, base_dir)
    os.makedirs(full, exist_ok=True)
    return full


def file_info(base_dir: str, rel_path: str) -> dict:
    full = safe_path(rel_path, base_dir)
    if not os.path.exists(full):
        return {"exists": False}
    stat = os.stat(full)
    return {
        "exists": True,
        "type": "dir" if os.path.isdir(full) else "file",
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "path": rel_path,
    }
