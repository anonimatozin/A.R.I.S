"""Plano leve da tarefa: estado + ferramenta interna ``plan_update`` (Risk.READ).

A ferramenta é registrada só na instância de registry do agente (nunca em
``aris_agent/tools/`` nem no ``discover`` global).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..contract.types import Risk, ToolResult, ToolSpec
from ..tools.registry import function_tool

if TYPE_CHECKING:
    from ..contract.types import ToolContext
    from .state import TaskState

STATUS_VALIDOS = ("todo", "doing", "done", "cancelled")

_ROTULOS = {
    "todo": "pendente",
    "doing": "em andamento",
    "done": "concluido",
    "cancelled": "cancelado",
}

PLAN_SPEC = ToolSpec(
    name="plan_update",
    description=(
        "Atualiza a lista de tarefas desta missao. Use em pedidos com 3 etapas ou mais: "
        "envie o plano completo (todos os itens) com o status de cada um."
    ),
    parameters={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Plano completo da tarefa, com todos os itens.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "o que fazer"},
                        "status": {"type": "string", "enum": list(STATUS_VALIDOS)},
                    },
                    "required": ["text", "status"],
                },
            }
        },
        "required": ["items"],
    },
    risk=Risk.READ,
    timeout_s=5.0,
    tags=("plano", "tarefas", "lista"),
)


@dataclass
class PlanState:
    """Plano atual da tarefa em andamento."""

    items: list[dict] = field(default_factory=list)
    version: int = 0

    def set(self, items: list) -> None:
        """Substitui o plano inteiro e incrementa a versão."""
        novos: list[dict] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            texto = str(item.get("text", "")).strip()
            status = str(item.get("status", "todo"))
            if texto:
                novos.append({"text": texto, "status": status if status in _ROTULOS else "todo"})
        self.items = novos
        self.version += 1

    def as_list(self) -> list[dict]:
        return [dict(item) for item in self.items]

    def as_text(self) -> str:
        """Plano para o prompt: uma linha por item com status legível."""
        return "\n".join(
            f"- [{_ROTULOS.get(str(item.get('status')), 'pendente')}] {item.get('text', '')}"
            for item in self.items
        )


def make_plan_tool(get_state):
    """Cria a ferramenta ``plan_update``; o estado vem do agente via ``get_state(session_id)``."""

    @function_tool(PLAN_SPEC)
    def plan_update(args: dict, ctx: ToolContext) -> ToolResult:
        state: TaskState | None = get_state(ctx.session_id)
        if state is None or not state.active:
            return ToolResult(ok=False, error="nenhuma tarefa ativa para atualizar o plano")
        state.plan.set(list(args.get("items") or []))
        state.emit("plan", {"items": state.plan.as_list(), "version": state.plan.version})
        return ToolResult(ok=True, content=state.plan.as_text() or "plano vazio")

    return plan_update


__all__ = ["PLAN_SPEC", "PlanState", "STATUS_VALIDOS", "make_plan_tool"]
