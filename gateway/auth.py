"""Authentication and authorization for CLL1 Gateway."""

from __future__ import annotations

import os

_TOKEN: str | None = None
_BASE_DIR: str = ""


def init_auth(base_dir: str) -> None:
    global _TOKEN, _BASE_DIR
    _BASE_DIR = base_dir
    _TOKEN = _load_token(base_dir)


def _load_token(base_dir: str) -> str | None:
    env_token = os.environ.get("CLL1_TOKEN")
    if env_token:
        return env_token

    env_file = os.path.join(base_dir, ".env")
    try:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("CLL1_TOKEN="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except FileNotFoundError:
        pass

    return None


def get_token() -> str | None:
    return _TOKEN


def authenticate(request: dict) -> bool:
    token = request.get("token", "")
    return bool(_TOKEN) and token == _TOKEN
