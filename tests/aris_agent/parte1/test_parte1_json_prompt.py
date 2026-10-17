"""Testes da emulação de ferramentas por JSON no prompt (tool_mode=json_prompt)."""

from __future__ import annotations

import pytest
from test_parte1_fake_server import FakeOpenAIServer, completion

from aris_agent.contract.errors import ProviderError
from aris_agent.contract.types import ChatMessage, Risk, ToolSpec
from aris_agent.llm.provider import OpenAICompatProvider
from aris_agent.llm.settings import ProviderConfig

SOMA = ToolSpec(
    name="soma",
    description="Soma dois inteiros.",
    parameters={
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
    },
    risk=Risk.READ,
)


def make_provider(server: FakeOpenAIServer, **overrides) -> OpenAICompatProvider:
    config = ProviderConfig(
        name="local",
        base_url=server.base_url,
        models=overrides.pop("models", ("modelo-local",)),
        tool_mode="json_prompt",
        **overrides,
    )
    return OpenAICompatProvider(config, sleeper=lambda _d: None, env={})


@pytest.fixture
def server():
    with FakeOpenAIServer() as fake:
        yield fake


def ask(provider: OpenAICompatProvider):
    return provider.chat(
        [ChatMessage(role="user", content="quanto é 2+3?")], [SOMA], max_tokens=128
    )


def test_ferramentas_vao_no_prompt_e_nao_no_parametro_tools(server) -> None:
    server.enqueue(payload=completion('{"final": "5"}'))
    provider = make_provider(server)
    ask(provider)

    body = server.requests[0]["body"]
    assert "tools" not in body
    assert "tool_choice" not in body
    system_messages = [m for m in body["messages"] if m["role"] == "system"]
    assert len(system_messages) == 1
    texto = system_messages[0]["content"]
    assert "soma" in texto
    assert '"tool_call"' in texto
    assert '"final"' in texto
    assert '"a"' in texto and '"b"' in texto


def test_envelope_tool_call_direto(server) -> None:
    server.enqueue(payload=completion('{"tool_call": {"name": "soma", "arguments": {"a": 2, "b": 3}}}'))
    provider = make_provider(server)
    response = ask(provider)

    assert response.finish_reason == "tool_calls"
    calls = response.message.tool_calls
    assert calls is not None and len(calls) == 1
    assert calls[0].name == "soma"
    assert calls[0].arguments == {"a": 2, "b": 3}
    assert calls[0].id.startswith("call_")


def test_envelope_com_cerca_de_codigo(server) -> None:
    corpo = '```json\n{"tool_call": {"name": "soma", "arguments": {"a": 1, "b": 4}}}\n```'
    server.enqueue(payload=completion(corpo))
    provider = make_provider(server)
    response = ask(provider)
    assert response.message.tool_calls is not None
    assert response.message.tool_calls[0].arguments == {"a": 1, "b": 4}


def test_envelope_reparado_aspas_simples_e_virgula_final(server) -> None:
    corpo = "{'tool_call': {'name': 'soma', 'arguments': {'a': 7, 'b': 8,}}}"
    server.enqueue(payload=completion(corpo))
    provider = make_provider(server)
    response = ask(provider)
    assert response.message.tool_calls is not None
    assert response.message.tool_calls[0].arguments == {"a": 7, "b": 8}


def test_envelope_com_texto_ao_redor(server) -> None:
    corpo = 'claro! aqui vai: {"tool_call": {"name": "soma", "arguments": {"a": 1, "b": 1}}} espero ter ajudado'
    server.enqueue(payload=completion(corpo))
    provider = make_provider(server)
    response = ask(provider)
    assert response.message.tool_calls is not None
    assert response.message.tool_calls[0].name == "soma"


def test_envelope_final_vai_para_content(server) -> None:
    server.enqueue(payload=completion('{"final": "o resultado é 5"}'))
    provider = make_provider(server)
    response = ask(provider)
    assert response.message.content == "o resultado é 5"
    assert response.message.tool_calls is None
    assert response.finish_reason == "stop"


def test_envelope_tool_calls_plural_tolerado(server) -> None:
    corpo = '{"tool_calls": [{"name": "soma", "arguments": {"a": 3, "b": 4}}]}'
    server.enqueue(payload=completion(corpo))
    provider = make_provider(server)
    response = ask(provider)
    assert response.message.tool_calls is not None
    assert response.message.tool_calls[0].arguments == {"a": 3, "b": 4}


def test_envelope_arguments_como_string(server) -> None:
    corpo = '{"tool_call": {"name": "soma", "arguments": "{\\"a\\": 5, \\"b\\": 5}"}}'
    server.enqueue(payload=completion(corpo))
    provider = make_provider(server)
    response = ask(provider)
    assert response.message.tool_calls is not None
    assert response.message.tool_calls[0].arguments == {"a": 5, "b": 5}


def test_texto_sem_json_falha_apos_uma_renovação(server) -> None:
    server.enqueue(payload=completion("desculpe, não entendi"))
    server.enqueue(payload=completion("desculpe, não entendi"))
    provider = make_provider(server)

    with pytest.raises(ProviderError) as excinfo:
        ask(provider)

    assert excinfo.value.kind == "tool_format"
    assert server.request_count == 2


def test_json_sem_tool_call_nem_final_falha(server) -> None:
    server.enqueue(payload=completion('{"pergunta": "e agora?"}'))
    server.enqueue(payload=completion('{"pergunta": "e agora?"}'))
    provider = make_provider(server)
    with pytest.raises(ProviderError) as excinfo:
        ask(provider)
    assert excinfo.value.kind == "tool_format"
    assert server.request_count == 2


def test_argumentos_nao_objeto_falha_como_tool_format(server) -> None:
    server.enqueue(payload=completion('{"tool_call": {"name": "soma", "arguments": [1, 2]}}'))
    server.enqueue(payload=completion('{"tool_call": {"name": "soma", "arguments": [1, 2]}}'))
    provider = make_provider(server)
    with pytest.raises(ProviderError) as excinfo:
        ask(provider)
    assert excinfo.value.kind == "tool_format"
