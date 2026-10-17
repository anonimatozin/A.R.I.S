"""Saída das ferramentas de web: truncamento + aviso de conteúdo não confiável."""

from __future__ import annotations

from ...config import AgentConfig
from ...contract.utils import truncate_text, wrap_untrusted


def wrap_result(text: str, source: str, config: AgentConfig, max_chars: int = 6000) -> str:
    """Trunca ``text`` e aplica ``wrap_untrusted`` respeitando ``max_tool_chars``."""
    inner_limit = max(200, min(int(max_chars), int(config.max_tool_chars) - 400))
    inner = truncate_text(text, inner_limit)
    out = wrap_untrusted(inner, source)
    if len(out) > config.max_tool_chars:
        out = truncate_text(out, config.max_tool_chars)
    return out
