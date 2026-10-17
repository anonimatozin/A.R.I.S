"""Configuração da seção ``safety`` do ``aris_agent.json``.

Todos os valores são opcionais; os padrões valem quando a seção não existe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import AgentConfig

log = logging.getLogger("aris.agent.safety.settings")

MODES = ("strict", "balanced", "readonly")

# Comandos que dispensam confirmação (lista de permissões de EXEC).
# Casa pelo 1º token ("dir") ou pelo início do comando ("git status").
DEFAULT_EXEC_ALLOWLIST: tuple[str, ...] = (
    "dir",
    "ls",
    "ver",
    "echo",
    "type",
    "hostname",
    "whoami",
    "pwd",
    "date",
    "findstr",
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git remote -v",
    "python --version",
    "py --version",
)

# Verbos de leitura usados só no modo balanced (com alvos dentro das raízes).
DEFAULT_BALANCED_VERBS: tuple[str, ...] = (
    "get-content",
    "get-childitem",
    "gci",
    "select-string",
    "cat",
    "head",
    "tail",
    "clear",
)


def _as_int(value: object, default: int, name: str) -> int:
    try:
        out = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning("safety.%s inválido: %r (usando %s)", name, value, default)
        return default
    if out <= 0:
        log.warning("safety.%s precisa ser > 0 (usando %s)", name, default)
        return default
    return out


def _as_float(value: object, default: float, name: str) -> float:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning("safety.%s inválido: %r (usando %s)", name, value, default)
        return default
    if out <= 0:
        log.warning("safety.%s precisa ser > 0 (usando %s)", name, default)
        return default
    return out


def _as_bool(value: object, default: bool, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "sim"}:
            return True
        if lowered in {"0", "false", "no", "off", "nao", "não"}:
            return False
    log.warning("safety.%s inválido: %r (usando %s)", name, value, default)
    return default


def _as_str_tuple(value: object, default: tuple[str, ...], name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = [str(v) for v in value]
    else:
        log.warning("safety.%s inválido: %r (usando padrão)", name, value)
        return default
    out = tuple(str(v).strip() for v in items if str(v).strip())
    return out or default


@dataclass
class SafetySettings:
    """Política de segurança lida de ``cfg.section("safety")``."""

    mode: str = "strict"
    exec_allowlist: tuple[str, ...] = DEFAULT_EXEC_ALLOWLIST
    balanced_verbs: tuple[str, ...] = DEFAULT_BALANCED_VERBS
    exec_per_minute: int = 10
    exec_per_task: int = 40
    repeat_limit: int = 3
    batch_path_threshold: int = 10
    audit_max_bytes: int = 2_000_000
    audit_preview: bool = False
    confirm_timeout_s: float | None = None  # None => cfg.confirm_timeout_s
    enable_hotkey: bool = False
    hotkey: str = "ctrl+alt+F12"

    @classmethod
    def from_section(cls, section: dict, config: AgentConfig) -> SafetySettings:
        """Monta as configurações a partir da seção ``safety`` (dict vazio = padrões)."""
        settings = cls()
        if not isinstance(section, dict) or not section:
            return settings

        mode = str(section.get("mode", settings.mode)).strip().lower()
        if mode not in MODES:
            log.warning("safety.mode=%r desconhecido; usando 'strict'", mode)
            mode = "strict"
        settings.mode = mode

        if "exec_allowlist" in section:
            settings.exec_allowlist = _as_str_tuple(
                section["exec_allowlist"], settings.exec_allowlist, "exec_allowlist"
            )
        if "balanced_verbs" in section:
            settings.balanced_verbs = _as_str_tuple(
                section["balanced_verbs"], settings.balanced_verbs, "balanced_verbs"
            )
        if "exec_per_minute" in section:
            settings.exec_per_minute = _as_int(
                section["exec_per_minute"], settings.exec_per_minute, "exec_per_minute"
            )
        if "exec_per_task" in section:
            settings.exec_per_task = _as_int(
                section["exec_per_task"], settings.exec_per_task, "exec_per_task"
            )
        if "repeat_limit" in section:
            settings.repeat_limit = _as_int(section["repeat_limit"], settings.repeat_limit, "repeat_limit")
        if "batch_path_threshold" in section:
            settings.batch_path_threshold = _as_int(
                section["batch_path_threshold"], settings.batch_path_threshold, "batch_path_threshold"
            )
        if "audit_max_bytes" in section:
            settings.audit_max_bytes = _as_int(
                section["audit_max_bytes"], settings.audit_max_bytes, "audit_max_bytes"
            )
        if "audit_preview" in section:
            settings.audit_preview = _as_bool(section["audit_preview"], settings.audit_preview, "audit_preview")
        if "confirm_timeout_s" in section:
            settings.confirm_timeout_s = _as_float(
                section["confirm_timeout_s"], 30.0, "confirm_timeout_s"
            )
        if "enable_hotkey" in section:
            settings.enable_hotkey = _as_bool(section["enable_hotkey"], settings.enable_hotkey, "enable_hotkey")
        if "hotkey" in section and str(section["hotkey"]).strip():
            settings.hotkey = str(section["hotkey"]).strip()
        return settings

    def resolve_confirm_timeout(self, config: AgentConfig) -> float:
        """Timeout de confirmação: ``safety.confirm_timeout_s`` ou o global."""
        if self.confirm_timeout_s is not None:
            return float(self.confirm_timeout_s)
        return float(config.confirm_timeout_s)
