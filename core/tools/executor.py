"""Tool Executor — executor unificado de tools com SecurityGate.

Todas as tools passam pelo SecurityGate. Sem excecao. Sem bypass.
"""

from __future__ import annotations

import time
from typing import Any

from core.neural.mode import ARISMode, get_mode_manager
from core.neural.capabilities import get_capability_registry
from core.tools.cll1_tools import CLL1_TOOLS, execute_cll1_tool
from core.tools.pc_tools import PC_TOOLS, execute_pc_tool
from core.tools.email_tools import EMAIL_TOOLS, execute_email_tool, EmailHandler
from core.tools.wol import execute_wol
from core.tools.pc_control import execute_pc_control
from core.tools.project_tools import PROJECT_TOOLS, execute_project_tool
from core.tools.intelligence_tools import INTELLIGENCE_TOOLS, execute_intel_tool


class ToolExecutor:
    """Executor unificado de tools com validacao de seguranca.

    Flow: tool_name → SecurityGate → capabilities check → execute → audit
    """

    def __init__(
        self,
        security_gate: Any = None,
        mode_manager: Any = None,
        capability_registry: Any = None,
        audit_logger: Any = None,
    ) -> None:
        self._security = security_gate
        self._mode_manager = mode_manager or get_mode_manager()
        self._capabilities = capability_registry or get_capability_registry()
        self._audit = audit_logger
        self._email_handler = EmailHandler()
        self._call_log: list[dict[str, Any]] = []

    def execute(self, tool_name: str, params: dict[str, Any] | None = None,
                user: str = "system") -> dict[str, Any]:
        """Executa uma tool com validacao completa.

        1. Verifica se a tool existe
        2. Verifica se esta disponivel no modo atual
        3. Verifica permissao via SecurityGate
        4. Verifica se requer confirmacao
        5. Executa
        6. Registra em audit
        """
        params = params or {}
        start = time.time()

        # 1. Verificar se a tool existe
        tool_info = self._get_tool_info(tool_name)
        if tool_info is None:
            result = {"ok": False, "error": f"Tool '{tool_name}' not found"}
            self._audit_call(tool_name, params, result, user, start)
            return result

        # 2. Verificar modo
        mode = self._mode_manager.mode if self._mode_manager else ARISMode.UNKNOWN
        # Se UNKNOWN, assumir PRIMARY (tools locais sempre disponiveis)
        check_mode = mode if mode != ARISMode.UNKNOWN else ARISMode.PRIMARY
        if not self._capabilities.is_available(tool_name, check_mode):
            result = {
                "ok": False,
                "error": f"Tool '{tool_name}' not available in {mode.value} mode",
            }
            self._audit_call(tool_name, params, result, user, start)
            return result

        # 3. SecurityGate
        if self._security:
            from core.neural.decision.decision_engine import Decision
            decision = Decision(
                module=tool_name,
                action="execute",
                parameters=params,
                source="tool_executor",
            )
            gate = self._security.approve(decision)
            if not gate.is_allowed:
                result = {
                    "ok": False,
                    "error": f"SecurityGate: {gate.reason}",
                    "outcome": gate.outcome.value,
                }
                self._audit_call(tool_name, params, result, user, start)
                return result

        # 4. Confirmacao (se necessaria) — ANTES de despachar
        if self._capabilities.requires_confirmation(tool_name):
            if not params.get("_confirmed"):
                # Para tools CRITICAL que ja tem confirmacao propria, despachar direto
                # (elas mesmas retornam requires_confirmation)
                critical_with_own_check = {
                    "pc_shutdown", "pc_restart", "pc_lock", "pc_sleep",
                    "wake_on_lan",
                }
                if tool_name not in critical_with_own_check:
                    return {
                        "ok": False,
                        "requires_confirmation": True,
                        "tool": tool_name,
                        "message": f"Tool '{tool_name}' requires explicit confirmation. Set _confirmed=true.",
                    }

        # 5. Executar
        result = self._dispatch(tool_name, params)
        self._audit_call(tool_name, params, result, user, start)
        return result

    def _dispatch(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Despacha para o executor correto."""
        if tool_name in CLL1_TOOLS:
            return execute_cll1_tool(tool_name, params)
        if tool_name in PC_TOOLS:
            return execute_pc_tool(tool_name, params)
        if tool_name in EMAIL_TOOLS:
            return execute_email_tool(tool_name, params, self._email_handler)
        if tool_name == "wake_on_lan":
            return execute_wol(params)
        if tool_name in ("pc_shutdown", "pc_restart", "pc_lock", "pc_sleep", "pc_status"):
            return execute_pc_control(tool_name, params)
        if tool_name in PROJECT_TOOLS:
            return execute_project_tool(tool_name, params)
        if tool_name in INTELLIGENCE_TOOLS:
            return execute_intel_tool(tool_name, params)
        return {"ok": False, "error": f"No executor for tool '{tool_name}'"}

    def _get_tool_info(self, name: str) -> dict[str, Any] | None:
        """Retorna info de uma tool."""
        if name in CLL1_TOOLS:
            return CLL1_TOOLS[name]
        if name in PC_TOOLS:
            return PC_TOOLS[name]
        if name in EMAIL_TOOLS:
            return EMAIL_TOOLS[name]
        if name in PROJECT_TOOLS:
            return PROJECT_TOOLS[name]
        if name in INTELLIGENCE_TOOLS:
            return INTELLIGENCE_TOOLS[name]
        if name == "wake_on_lan":
            return {"permission": "critical", "description": "Ligar PC remotamente"}
        return None

    def _audit_call(self, tool: str, params: dict, result: dict,
                    user: str, start: float) -> None:
        """Registra chamada de tool em audit."""
        duration = int((time.time() - start) * 1000)
        entry = {
            "timestamp": time.time(),
            "tool": tool,
            "parameters_redacted": _redact(params),
            "success": result.get("ok", False),
            "duration_ms": duration,
            "user": user,
            "mode": self._mode_manager.mode.value if self._mode_manager else "unknown",
        }
        self._call_log.append(entry)
        if len(self._call_log) > 200:
            self._call_log = self._call_log[-200:]

        if self._audit:
            try:
                self._audit(
                    "tool_call",
                    tool=tool,
                    success=result.get("ok", False),
                    duration_ms=duration,
                )
            except Exception:
                pass

    def get_recent_calls(self, limit: int = 20) -> list[dict[str, Any]]:
        """Retorna chamadas recentes (para dashboard)."""
        return self._call_log[-limit:]

    def list_available_tools(self) -> dict[str, list[str]]:
        """Lista tools disponiveis no modo atual."""
        mode = self._mode_manager.mode if self._mode_manager else ARISMode.UNKNOWN
        # Se UNKNOWN, mostrar PRIMARY
        check_mode = mode if mode != ARISMode.UNKNOWN else ARISMode.PRIMARY
        caps = self._capabilities.available_in_mode(check_mode)
        return {c.name: [c.permission.value, c.description] for c in caps}


def _redact(params: dict[str, Any]) -> dict[str, Any]:
    """Redata parametros sensiveis."""
    sensitive = {"password", "token", "secret", "key", "credential", "auth"}
    return {
        k: "***" if any(s in k.lower() for s in sensitive) else v
        for k, v in params.items()
    }


_executor: ToolExecutor | None = None


def get_tool_executor() -> ToolExecutor:
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor
