"""Dono: Parte 7 — núcleo do agente (laço planejar → agir → verificar).

O laço vive em ``agent.ArisAgent``; os demais módulos são peças pequenas e
testáveis (prompt, seleção de ferramentas, plano, contexto, trace).
"""

from __future__ import annotations

from .agent import ArisAgent
from .context import ContextManager, estimate_messages, estimate_tokens
from .heuristics import asks_to_verify, choose_difficulty, looks_like_correction, looks_trivial
from .plan import PLAN_SPEC, PlanState, make_plan_tool
from .prompts import PromptBuilder, verification_messages
from .selector import CORE, MAX_TOOLS, ToolSelector
from .state import Emitter, TaskState
from .trace import TraceWriter
from .validation import validate_args

__all__ = [
    "CORE",
    "MAX_TOOLS",
    "PLAN_SPEC",
    "ArisAgent",
    "ContextManager",
    "Emitter",
    "PlanState",
    "PromptBuilder",
    "TaskState",
    "ToolSelector",
    "TraceWriter",
    "asks_to_verify",
    "choose_difficulty",
    "estimate_messages",
    "estimate_tokens",
    "looks_like_correction",
    "looks_trivial",
    "make_plan_tool",
    "validate_args",
    "verification_messages",
]
