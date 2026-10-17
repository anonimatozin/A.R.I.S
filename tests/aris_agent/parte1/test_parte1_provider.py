"""Testes do ``OpenAICompatProvider`` contra um servidor HTTP falso local."""

from __future__ import annotations

import logging

import pytest
from test_parte1_fake_server import (
    FakeOpenAIServer,
    completion,
    error,
    free_port,
    rate_limit,
    tool_call_completion,
)

from aris_agent.contract.errors import ProviderError
from aris_agent.contract.types import ChatMessage, Risk, ToolCall, ToolSpec
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


class Sleeper:
    """Sleeper falso: só registra as esperas (nenhum sleep real)."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def make_provider(server: FakeOpenAIServer, sleeper: Sleeper | None = None, **overrides) -> OpenAICompatProvider:
    config = ProviderConfig(
        name=overrides.pop("name", "fake"),
        base_url=server.base_url,
        models=overrides.pop("models", ("modelo-teste",)),
        api_key_env=overrides.pop("api_key_env", None),
        **overrides,
    )
    return OpenAICompatProvider(config, sleeper=sleeper or Sleeper(), env={})


def chat(provider: OpenAICompatProvider, tools=None, **kwargs):
    kwargs.setdefault("max_tokens", 32)
    return provider.chat([ChatMessage(role="user", content="olá")], tools, **kwargs)


@pytest.fixture
def server():
    with FakeOpenAIServer() as fake:
        yield fake


def test_resposta_normal(server) -> None:
    server.enqueue(payload=completion("oi, tudo bem?"))
    provider = make_provider(server)
    response = chat(provider)

    assert response.provider == "fake"
    assert response.model == "modelo-teste"
    assert response.message.role == "assistant"
    assert response.message.content == "oi, tudo bem?"
    assert response.message.tool_calls is None
    assert response.finish_reason == "stop"
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 6

    body = server.requests[0]["body"]
    assert body["model"] == "modelo-teste"
    assert body["messages"] == [{"role": "user", "content": "olá"}]
    assert body["max_tokens"] == 32
    assert "tools" not in body


def test_conversa_com_tool_calls_e_resultado(server) -> None:
    server.enqueue(payload=completion("ok"))
    provider = make_provider(server)
    provider.chat(
        [
            ChatMessage(role="system", content="você é a ARIS"),
            ChatMessage(role="user", content="soma 2 e 3"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call_9", name="soma", arguments={"a": 2, "b": 3})],
            ),
            ChatMessage(role="tool", content="5", tool_call_id="call_9", name="soma"),
        ]
    )
    body = server.requests[0]["body"]
    assert body["messages"][0] == {"role": "system", "content": "você é a ARIS"}
    assert body["messages"][2]["tool_calls"][0]["function"] == {
        "name": "soma",
        "arguments": '{"a": 2, "b": 3}',
    }
    assert body["messages"][3] == {
        "role": "tool",
        "content": "5",
        "tool_call_id": "call_9",
        "name": "soma",
    }


def test_tool_calls_convertidos_para_tool_call(server) -> None:
    server.enqueue(payload=tool_call_completion("soma", '{"a": 2, "b": 3}'))
    provider = make_provider(server)
    response = chat(provider, [SOMA])

    calls = response.message.tool_calls
    assert calls is not None and len(calls) == 1
    assert calls[0].name == "soma"
    assert calls[0].arguments == {"a": 2, "b": 3}
    assert calls[0].id == "call_1"
    assert response.finish_reason == "tool_calls"

    body = server.requests[0]["body"]
    assert body["tools"][0]["type"] == "function"
    assert body["tools"][0]["function"]["name"] == "soma"
    assert body["tool_choice"] == "auto"


def test_argumentos_com_json_invalido_vira_tool_format(server) -> None:
    server.enqueue(payload=tool_call_completion("soma", "{nao é json"))
    server.enqueue(payload=tool_call_completion("soma", "{nao é json"))
    provider = make_provider(server)

    with pytest.raises(ProviderError) as excinfo:
        chat(provider, [SOMA])

    assert excinfo.value.kind == "tool_format"
    assert "JSON" in str(excinfo.value)
    assert server.request_count == 2  # uma nova tentativa antes de falhar


def test_400_failed_generation_renova_uma_vez_com_temperatura_menor(server) -> None:
    server.enqueue(
        error(
            400,
            "Failed to call a function. See 'failed_generation'.",
            code="tool_use_failed",
            failed_generation={"reason": "Tool call arguments are not valid JSON"},
        )
    )
    server.enqueue(payload=completion("agora foi"))
    sleeper = Sleeper()
    provider = make_provider(server, sleeper)

    response = chat(provider, [SOMA], temperature=0.7)

    assert response.message.content == "agora foi"
    assert server.request_count == 2
    assert sleeper.delays == []  # a nova tentativa de tool não espera
    primeira = server.requests[0]["body"]["temperature"]
    segunda = server.requests[1]["body"]["temperature"]
    assert segunda == pytest.approx(primeira - 0.2)


def test_400_failed_generation_persistente_falha_com_tool_format(server) -> None:
    server.enqueue(error(400, "tool call validation failed", code="tool_use_failed"))
    server.enqueue(error(400, "tool call validation failed", code="tool_use_failed"))
    provider = make_provider(server)

    with pytest.raises(ProviderError) as excinfo:
        chat(provider, [SOMA])

    assert excinfo.value.kind == "tool_format"
    assert server.request_count == 2  # exatamente UMA nova tentativa


def test_400_comum_e_bad_request_sem_retry(server) -> None:
    server.enqueue(error(400, "campo inválido"))
    provider = make_provider(server)

    with pytest.raises(ProviderError) as excinfo:
        chat(provider)

    assert excinfo.value.kind == "bad_request"
    assert server.request_count == 1


def test_429_respeita_retry_after(server) -> None:
    server.enqueue(rate_limit(retry_after="2"))
    server.enqueue(payload=completion("deu certo"))
    sleeper = Sleeper()
    provider = make_provider(server, sleeper)

    response = chat(provider)

    assert response.message.content == "deu certo"
    assert server.request_count == 2
    assert sleeper.delays == [2.0]


def test_500_depois_sucesso_com_backoff(server) -> None:
    server.enqueue(error(500, "erro interno"))
    server.enqueue(payload=completion("ok"))
    sleeper = Sleeper()
    provider = make_provider(server, sleeper, backoff_base_s=1.0)

    response = chat(provider)

    assert response.message.content == "ok"
    assert len(sleeper.delays) == 1
    assert 1.0 <= sleeper.delays[0] <= 2.0  # base * 2^0 + jitter


def test_500_sempre_falha_como_server(server) -> None:
    for _ in range(5):
        server.enqueue(error(500, "erro interno"))
    sleeper = Sleeper()
    provider = make_provider(server, sleeper, max_attempts=3)

    with pytest.raises(ProviderError) as excinfo:
        chat(provider)

    assert excinfo.value.kind == "server"
    assert server.request_count == 3
    assert len(sleeper.delays) == 2


def test_401_e_auth_sem_retry(server) -> None:
    server.enqueue(error(401, "chave inválida"))
    sleeper = Sleeper()
    provider = make_provider(server, sleeper)

    with pytest.raises(ProviderError) as excinfo:
        chat(provider)

    assert excinfo.value.kind == "auth"
    assert server.request_count == 1
    assert sleeper.delays == []


def test_conexao_recusada_e_network() -> None:
    config = ProviderConfig(
        name="morto", base_url=f"http://127.0.0.1:{free_port()}/v1", models=("m",)
    )
    provider = OpenAICompatProvider(config, sleeper=lambda _d: None, env={})
    with pytest.raises(ProviderError) as excinfo:
        chat(provider)
    assert excinfo.value.kind == "network"


def test_timeout_e_network_sem_repetir(server) -> None:
    server.enqueue(delay=0.5, payload=completion("tarde demais"))
    provider = make_provider(server, timeout_s=0.05, max_attempts=1)

    with pytest.raises(ProviderError) as excinfo:
        chat(provider)

    assert excinfo.value.kind == "network"
    assert "timeout" in str(excinfo.value)


def test_provedor_sem_chave_fica_desativado(caplog) -> None:
    config = ProviderConfig(
        name="groq", base_url="http://127.0.0.1:1/v1", api_key_env="CHAVE_TESTE", models=("m",)
    )
    provider = OpenAICompatProvider(config, env={})
    assert provider.enabled is False
    assert "CHAVE_TESTE" in (provider.status() or "")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ProviderError) as excinfo:
            chat(provider)
    assert excinfo.value.kind == "auth"
    assert "desativado" in str(excinfo.value)
    assert any("CHAVE_TESTE" in record.message for record in caplog.records)


def test_provedor_local_sem_api_key_env_e_ativo() -> None:
    config = ProviderConfig(name="ollama", base_url="http://127.0.0.1:11434/v1", models=("m",))
    provider = OpenAICompatProvider(config, env={})
    assert provider.enabled is True
    assert provider.status() is None
    assert provider.api_key() is None


def test_chave_lida_da_variavel_e_header_enviado(server) -> None:
    server.enqueue(payload=completion("ok"))
    config = ProviderConfig(
        name="fake",
        base_url=server.base_url,
        api_key_env="CHAVE_SECRETA",
        models=("modelo-teste",),
    )
    provider = OpenAICompatProvider(config, env={"CHAVE_SECRETA": "gsk_supersecreta12345"})
    chat(provider)
    assert server.requests[0]["headers"].get("Authorization") == "Bearer gsk_supersecreta12345"


def test_nunca_loga_chave_nem_header(server, caplog) -> None:
    server.enqueue(error(500, "boom"))
    server.enqueue(error(500, "boom"))
    server.enqueue(error(500, "boom"))
    config = ProviderConfig(
        name="fake",
        base_url=server.base_url,
        api_key_env="CHAVE_SECRETA",
        models=("modelo-teste",),
        max_attempts=2,
    )
    provider = OpenAICompatProvider(config, env={"CHAVE_SECRETA": "gsk_supersecreta12345"})

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ProviderError):
            chat(provider)

    assert caplog.records
    for record in caplog.records:
        text = f"{record.getMessage()} {record.args!r}" if record.args else record.getMessage()
        assert "gsk_supersecreta12345" not in text
        assert "Bearer" not in text
        assert "Authorization" not in text


def test_resposta_sem_choices_e_server(server) -> None:
    server.enqueue(payload={"model": "modelo-teste", "choices": []})
    provider = make_provider(server, max_attempts=1)
    with pytest.raises(ProviderError) as excinfo:
        chat(provider)
    assert excinfo.value.kind == "server"
    assert "choices" in str(excinfo.value)


def test_resposta_json_inesperada_e_server(server) -> None:
    server.enqueue(payload="texto cru")  # JSON válido, mas não é objeto
    provider = make_provider(server, max_attempts=1)
    with pytest.raises(ProviderError) as excinfo:
        chat(provider)
    assert excinfo.value.kind == "server"


def test_request_vai_para_o_endpoint_certo(server) -> None:
    server.enqueue(payload=completion("primeira"))
    provider = make_provider(server)
    chat(provider)
    assert server.request_count == 1
    assert server.requests[0]["path"] == "/v1/chat/completions"
