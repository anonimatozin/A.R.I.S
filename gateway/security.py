"""Security utilities — path traversal prevention, input sanitization."""

from __future__ import annotations

import os
import re
import shlex


class PathTraversalError(Exception):
    pass


class CommandInjectionError(Exception):
    pass


def safe_path(path: str, base_dir: str) -> str:
    import pathlib as _pl
    if os.path.isabs(path):
        raise PathTraversalError(f"Absolute path not allowed: {path}")

    normalized = os.path.normpath(path)
    if normalized.startswith("..") or os.sep + ".." in normalized:
        raise PathTraversalError(f"Path traversal detected: {path}")

    base = os.path.realpath(os.path.abspath(base_dir))
    full = os.path.realpath(os.path.abspath(os.path.join(base, normalized)))

    # Resolve symlinks quando o alvo já existe (evita fuga via junção/symlink)
    try:
        full_resolved = str(_pl.Path(os.path.join(base, normalized)).resolve())
        if not (full_resolved == base or full_resolved.startswith(base + os.sep)):
            raise PathTraversalError(f"Path escapes sandbox (symlink): {path}")
        full = full_resolved
    except PathTraversalError:
        raise
    except Exception:
        if not (full == base or full.startswith(base + os.sep)):
            raise PathTraversalError(f"Path escapes sandbox: {path}")

    return full


def sanitize_command(command: str) -> str:
    if not command or not command.strip():
        raise CommandInjectionError("Empty command")
    if len(command) > 2000:
        raise CommandInjectionError("Command too long")

    # Bloquear metacaracteres de shell — execução é sem shell, então
    # qualquer tentativa de encadear/compor comando é rejeitada.
    shell_meta = [";", "&&", "||", "|", "`", "$(", "${", ">", "<", "\n", "\r"]
    for meta in shell_meta:
        if meta in command:
            raise CommandInjectionError(f"Shell metacharacter not allowed: {meta!r}")
    # $VAR isolado também é vetor (expansão); bloquear $ seguido de letra/paren
    if re.search(r"\$[\w\(\{]", command):
        raise CommandInjectionError("Shell expansion not allowed: $")

    dangerous = [
        r";\s*rm\s", r"\|\s*rm\s", r"`.*rm.*`",
        r"\$\(", r">\s*/etc/", r"mkfs", r"dd\s+if=",
        r":\(\)\{", r"fork\s*bomb",
    ]
    for pattern in dangerous:
        if re.search(pattern, command, re.IGNORECASE):
            raise CommandInjectionError(f"Dangerous command pattern: {pattern}")

    return command


def validate_command(command: str, allowlist: list[str] | None = None) -> str:
    command = sanitize_command(command)

    if allowlist:
        parts = shlex.split(command)
        if parts and parts[0] not in allowlist:
            raise CommandInjectionError(f"Command not in allowlist: {parts[0]}")

    return command
