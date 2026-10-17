"""Dono: Parte 5 — segurança: ToolExecutor, política de confirmação e auditoria.

Exposição principal: ``SafeExecutor`` (implementa ``ToolExecutor`` do contrato).
"""

from __future__ import annotations

from .audit import AuditLogger
from .confirm import cli_confirm, format_request, make_cli_confirm
from .executor import SafeExecutor
from .injection import scan_untrusted
from .killswitch import KillSwitch
from .limits import LoopGuard
from .policy import Decision, PolicyEngine
from .settings import SafetySettings

__all__ = [
    "AuditLogger",
    "Decision",
    "KillSwitch",
    "LoopGuard",
    "PolicyEngine",
    "SafeExecutor",
    "SafetySettings",
    "cli_confirm",
    "format_request",
    "make_cli_confirm",
    "scan_untrusted",
]
