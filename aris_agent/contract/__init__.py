"""Reexporta os tipos, interfaces, erros e utilitários do contrato."""

from __future__ import annotations

from .errors import ArisAgentError, PolicyDenied, ProviderError, ProviderKind, ToolError
from .protocols import Agent, LLMClient, Memory, SkillCatalog, Tool, ToolExecutor
from .types import (
    AgentEvent,
    AgentResult,
    ChatMessage,
    ConfirmFn,
    ConfirmRequest,
    EventSink,
    LLMResponse,
    MemoryItem,
    Risk,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSpec,
    Usage,
)
from .utils import REDACTED, redact_secrets, truncate_text, wrap_untrusted

__all__ = [
    "Agent",
    "AgentEvent",
    "AgentResult",
    "ArisAgentError",
    "ChatMessage",
    "ConfirmFn",
    "ConfirmRequest",
    "EventSink",
    "LLMClient",
    "LLMResponse",
    "Memory",
    "MemoryItem",
    "PolicyDenied",
    "ProviderError",
    "ProviderKind",
    "REDACTED",
    "Risk",
    "SkillCatalog",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolError",
    "ToolExecutor",
    "ToolResult",
    "ToolSpec",
    "Usage",
    "redact_secrets",
    "truncate_text",
    "wrap_untrusted",
]
