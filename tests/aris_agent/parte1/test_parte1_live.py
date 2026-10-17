"""Testes ao vivo contra a API real (pulados por padrão).

Ative com ``ARIS_TEST_LIVE=1`` ou ``-m live``. Usa as chaves que já estiverem
no ambiente; se não houver provedor ativo, o teste é pulado com aviso.
"""

from __future__ import annotations

import os

import pytest

from aris_agent.config import load_config
from aris_agent.contract.types import ChatMessage, Risk, ToolSpec
from aris_agent.llm.router import build_router

pytestmark = pytest.mark.live

_SOMA = ToolSpec(
    name="soma",
    description="Soma dois inteiros.",
    parameters={
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    },
    risk=Risk.READ,
    tags=("demo",),
)


def _router_ativo():
    cfg = load_config()
    router = build_router(cfg)
    ativos = [
        name for name, provider in router.providers.items() if provider.status() is None
    ]
    if not ativos:
        router.close()
        pytest.skip("nenhum provedor ativo no ambiente (defina a chave ou ARIS_AGENT_*)")
    return router


def test_chat_ao_vivo() -> None:
    router = _router_ativo()
    try:
        response = router.chat(
            [ChatMessage(role="user", content="Responda apenas: ok")],
            difficulty=os.environ.get("ARIS_LIVE_DIFFICULTY", "normal"),
            max_tokens=32,
        )
    finally:
        router.close()
    assert response.message.content
    assert response.provider
    assert response.usage.prompt_tokens >= 0


def test_tool_call_ao_vivo() -> None:
    router = _router_ativo()
    try:
        response = router.chat(
            [
                ChatMessage(role="system", content="Você usa ferramentas quando precisar."),
                ChatMessage(
                    role="user", content="Use a ferramenta soma para calcular 2+3."
                ),
            ],
            [_SOMA],
            difficulty=os.environ.get("ARIS_LIVE_DIFFICULTY", "normal"),
            max_tokens=256,
        )
    finally:
        router.close()
    calls = response.message.tool_calls
    if not calls:
        pytest.skip(f"o modelo {response.provider}:{response.model} não chamou a ferramenta")
    assert calls[0].name == "soma"
