"""Testes dos dublês (Parte 0)."""

from __future__ import annotations

import threading

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.errors import ProviderError
from aris_agent.contract.types import (
    ChatMessage,
    ConfirmRequest,
    Risk,
    ToolCall,
    ToolContext,
    ToolResult,
)
from aris_agent.fakes import (
    AutoConfirm,
    EchoTool,
    FakeLLM,
    FakeMemory,
    FakeSkills,
    PassthroughExecutor,
)
from aris_agent.tools import ToolRegistry


def make_ctx(tmp_path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(session_id="s1", workdir=tmp_path, config=cfg, cancel=threading.Event())


def test_fake_llm_ordem_do_roteiro() -> None:
    roteiro = [
        ChatMessage(role="assistant", content="primeira"),
        ChatMessage(role="assistant", content="segunda"),
    ]
    llm = FakeLLM(roteiro)
    r1 = llm.chat([ChatMessage(role="user", content="oi")])
    r2 = llm.chat([ChatMessage(role="user", content="oi")])
    assert r1.message.content == "primeira"
    assert r2.message.content == "segunda"
    assert r1.provider == "fake" and r1.model == "fake"
    assert llm.remaining == 0
    assert len(llm.calls) == 2
    assert llm.calls[0]["messages"][0].content == "oi"
    assert llm.calls[0]["difficulty"] == "normal"


def test_fake_llm_com_tool_calls() -> None:
    call = ToolCall(id="c1", name="echo", arguments={"a": 1})
    llm = FakeLLM([ChatMessage(role="assistant", tool_calls=[call])])
    resp = llm.chat([], tools=None, difficulty="hard", max_tokens=99, temperature=0.0)
    assert resp.message.tool_calls and resp.message.tool_calls[0].name == "echo"
    assert resp.finish_reason == "tool_calls"
    assert llm.calls[0]["difficulty"] == "hard"
    assert llm.calls[0]["max_tokens"] == 99
    assert llm.calls[0]["temperature"] == 0.0


def test_fake_llm_roteiro_esgotado() -> None:
    llm = FakeLLM()
    with pytest.raises(ProviderError) as exc:
        llm.chat([])
    assert exc.value.kind == "server"


def test_fake_memory_crud_e_turnos() -> None:
    mem = FakeMemory()
    ident = mem.remember("usuário gosta de café", kind="preference", tags=("café",))
    items = mem.recall("café")
    assert items and items[0].id == ident
    assert mem.forget(ident) is True
    assert mem.forget(ident) is False
    assert mem.recall("café") == []

    mem.add_turn("s1", "user", "olá")
    mem.add_turn("s1", "assistant", "oi!")
    assert len(mem.recent_turns("s1")) == 2
    assert [m.role for m in mem.recent_turns("s1", 1)] == ["assistant"]
    assert mem.recent_turns("outra") == []


def test_fake_memory_filtro_por_kind() -> None:
    mem = FakeMemory()
    mem.remember("gosto de pizza", kind="fact")
    mem.remember("gosto de chá", kind="preference")
    achados = mem.recall("gosto", kinds=("preference",))
    assert len(achados) == 1
    assert achados[0].kind == "preference"


def test_fake_skills() -> None:
    skills = FakeSkills()
    skills.add("pesquisar", "pesquisa na web", "corpo da skill")
    skills.add("email", "envia e-mail", "outro corpo")
    assert skills.names() == ["email", "pesquisar"]
    assert "pesquisar: pesquisa na web" in skills.catalog_prompt()
    assert skills.load("email") == "outro corpo"
    with pytest.raises(KeyError):
        skills.load("nao_existe")


def test_echo_tool(tmp_path) -> None:
    result = EchoTool().run({"b": 2, "a": 1}, make_ctx(tmp_path))
    assert result.ok
    assert '"a": 1' in result.content and '"b": 2' in result.content
    assert result.data == {"b": 2, "a": 1}


def test_auto_confirm() -> None:
    confirm = AutoConfirm(False)
    req = ConfirmRequest(tool_name="x", args_preview="...", risk=Risk.DESTRUCTIVE, reason="...")
    assert confirm(req) is False
    assert confirm.requests == [req]
    assert AutoConfirm()(req) is True


def test_passthrough_executor(tmp_path) -> None:
    registry = ToolRegistry([EchoTool()])
    executor = PassthroughExecutor(registry)
    ctx = make_ctx(tmp_path)
    ok = executor.execute(ToolCall(id="1", name="echo", arguments={"x": 1}), ctx, None)
    assert ok.ok and ok.data == {"x": 1}

    falha = executor.execute(ToolCall(id="2", name="inexistente", arguments={}), ctx, None)
    assert falha.ok is False and "desconhecida" in (falha.error or "")
    assert len(executor.calls) == 2


def test_passthrough_executor_sem_registry(tmp_path) -> None:
    executor = PassthroughExecutor()
    result = executor.execute(
        ToolCall(id="1", name="echo", arguments={}), make_ctx(tmp_path), None
    )
    assert result.ok is False


def test_passthrough_executor_converte_excecao(tmp_path) -> None:
    class Bomba:
        spec = EchoTool.spec

        def run(self, args, ctx):
            raise ValueError("estourou")

    registry = ToolRegistry()
    registry.register(Bomba())
    executor = PassthroughExecutor(registry)
    result = executor.execute(ToolCall(id="1", name="echo", arguments={}), make_ctx(tmp_path), None)
    assert result.ok is False
    assert "ValueError" in (result.error or "")


def test_tool_result_padrao() -> None:
    result = ToolResult(ok=True, content="x")
    assert result.data is None and result.error is None and result.artifacts == []
