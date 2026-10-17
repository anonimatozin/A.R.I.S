"""Contexto: orçamento estimado de tokens e compactação das mensagens antigas da tarefa."""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..contract.types import ChatMessage
from ..contract.utils import truncate_text

log = logging.getLogger("aris.agent.core.context")

# Resumidor devolve o texto do resumo ou None (falhou / já resumiu).
Summarizer = Callable[[list[ChatMessage]], str | None]


def estimate_tokens(text: str | None) -> int:
    """Estimativa barata de tokens (~4 caracteres por token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_messages(messages: list[ChatMessage]) -> int:
    """Estimativa de tokens de uma lista de mensagens (conteúdo + overhead)."""
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.content) + 4
        for call in msg.tool_calls or []:
            total += 8 + estimate_tokens(call.name) + estimate_tokens(str(call.arguments))
    return total


class ContextManager:
    """Mantém o histórico dentro de um orçamento de tokens estimado.

    Ao estourar, resume as mensagens antigas da tarefa numa só (``summarizer``),
    preservando o system, o pedido atual e as últimas mensagens. Compacta no
    máximo uma vez por tarefa — resumir de novo só jogaria fora o resumo.
    """

    def __init__(self, max_tokens: int = 12000, keep_recent: int = 6) -> None:
        self.max_tokens = max(1, int(max_tokens))
        self.keep_recent = max(2, int(keep_recent))
        self.compacted = False

    def fit(
        self,
        messages: list[ChatMessage],
        summarizer: Summarizer | None = None,
    ) -> list[ChatMessage]:
        """Devolve o histórico dentro do orçamento (pode ser a própria lista)."""
        msgs = list(messages)
        if estimate_messages(msgs) <= self.max_tokens:
            return msgs
        if self.compacted:
            log.debug("contexto acima do orçamento mas já resumido nesta tarefa")
            return msgs

        head = [msgs[0]] if msgs and msgs[0].role == "system" else []
        start = len(head)
        if len(msgs) <= start + 1:
            return msgs

        # A cauda precisa começar num dono de tool: nunca deixe tool órfã.
        tail_start = max(start, len(msgs) - self.keep_recent)
        while tail_start > start and msgs[tail_start].role == "tool":
            tail_start -= 1

        # O pedido atual (última mensagem user) nunca é resumido.
        pinned_idx = None
        for index in range(len(msgs) - 1, start - 1, -1):
            if msgs[index].role == "user":
                pinned_idx = index
                break

        middle = [msgs[i] for i in range(start, tail_start) if i != pinned_idx]
        if not middle:
            log.warning(
                "contexto acima do orçamento (%d tokens) mas nada antigo a compactar",
                estimate_messages(msgs),
            )
            return msgs

        resumo = summarizer(middle) if summarizer else None
        if not resumo:
            resumo = f"[historico anterior removido por limite de contexto: {len(middle)} mensagens]"
        mensagem_resumo = ChatMessage(role="user", content=truncate_text(resumo, 2000))
        final = msgs[tail_start:]
        self.compacted = True
        log.debug("contexto compactado: %d -> %d mensagens", len(msgs), len(head) + 2 + len(final))
        if pinned_idx is not None and pinned_idx < tail_start:
            return head + [msgs[pinned_idx], mensagem_resumo] + final
        return head + [mensagem_resumo] + final


__all__ = ["ContextManager", "Summarizer", "estimate_messages", "estimate_tokens"]
