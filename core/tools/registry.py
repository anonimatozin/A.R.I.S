"""Tool Registry — registro unificado de todas as tools do sistema.

Fluxo: Usuario → LLM → decide tool → SecurityGate → executa tool → resultado →
       LLM → decide proxima tool → ... → tarefa concluida.

Arquitetura propria, nao copiada de projetos de terceiros.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.neural.capabilities import get_capability_registry, PermissionLevel
from core.neural.mode import get_mode_manager, ARISMode


@dataclass
class ToolDefinition:
    """Definicao de uma tool registrada."""
    name: str
    description: str
    permission: PermissionLevel
    modes: tuple[str, ...]
    category: str
    requires_confirmation: bool = False
    parameters_schema: dict[str, Any] | None = None
    executor: Callable[..., dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission.value,
            "modes": list(self.modes),
            "category": self.category,
            "requires_confirmation": self.requires_confirmation,
        }


class ToolRegistry:
    """Registro unificado de tools do A.R.I.S.

    Centraliza todas as tools (CLL1, PC, Email, WoL, PC Control)
    em um unico registro consultavel pelo LLM e pelo AgentLoop.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._register_from_modules()

    def _register_from_modules(self) -> None:
        """Registra tools de todos os modulos."""
        # CLL1 Tools
        from core.tools.cll1_tools import CLL1_TOOLS
        for name, info in CLL1_TOOLS.items():
            perm = PermissionLevel(info["permission"])
            self._tools[name] = ToolDefinition(
                name=name,
                description=info["description"],
                permission=perm,
                modes=("edge", "primary"),
                category="cll1",
                executor=info["fn"],
            )

        # PC Tools
        from core.tools.pc_tools import PC_TOOLS
        for name, info in PC_TOOLS.items():
            perm = PermissionLevel(info["permission"])
            self._tools[name] = ToolDefinition(
                name=name,
                description=info["description"],
                permission=perm,
                modes=("primary",),
                category="pc",
                requires_confirmation=perm in (PermissionLevel.HIGH, PermissionLevel.CRITICAL),
                executor=info["fn"],
            )

        # Email Tools
        from core.tools.email_tools import EMAIL_TOOLS
        for name, info in EMAIL_TOOLS.items():
            perm = PermissionLevel(info["permission"])
            self._tools[name] = ToolDefinition(
                name=name,
                description=info["description"],
                permission=perm,
                modes=("edge", "primary"),
                category="email",
                executor=None,
            )

        # WoL
        self._tools["wake_on_lan"] = ToolDefinition(
            name="wake_on_lan",
            description="Ligar PC remotamente via Wake-on-LAN",
            permission=PermissionLevel.CRITICAL,
            modes=("edge",),
            category="wol",
            requires_confirmation=True,
        )

        # Core capabilities (chat, memory, etc)
        cr = get_capability_registry()
        for name, cap in cr._capabilities.items():
            if name not in self._tools:
                self._tools[name] = ToolDefinition(
                    name=name,
                    description=cap.description,
                    permission=cap.permission,
                    modes=cap.modes,
                    category=cap.category,
                    requires_confirmation=cap.requires_confirmation,
                )

        # Intelligence Tools (internal)
        from core.tools.intelligence_tools import INTELLIGENCE_TOOLS
        for name, info in INTELLIGENCE_TOOLS.items():
            perm = PermissionLevel(info["permission"])
            self._tools[name] = ToolDefinition(
                name=name,
                description=info["description"],
                permission=perm,
                modes=("edge", "primary"),
                category=info["category"],
            )

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def available_for_mode(self, mode: ARISMode | None = None) -> list[ToolDefinition]:
        """Tools disponiveis no modo atual."""
        if mode is None:
            mode = get_mode_manager().mode
        return [t for t in self._tools.values() if mode.value in t.modes]

    def by_category(self, mode: ARISMode | None = None) -> dict[str, list[ToolDefinition]]:
        """Agrupa tools por categoria."""
        tools = self.available_for_mode(mode) if mode else self.list_tools()
        result: dict[str, list[ToolDefinition]] = {}
        for t in tools:
            result.setdefault(t.category, []).append(t)
        return result

    def to_llm_schema(self, mode: ARISMode | None = None) -> str:
        """Schema formatado para incluir no prompt do LLM."""
        tools = self.available_for_mode(mode)
        lines = []
        for t in sorted(tools, key=lambda x: x.category):
            conf = " [REQUIRES CONFIRMATION]" if t.requires_confirmation else ""
            lines.append(f"- {t.name}: {t.description} (permission: {t.permission.value}){conf}")
        return "\n".join(lines)

    def count(self) -> int:
        return len(self._tools)


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
