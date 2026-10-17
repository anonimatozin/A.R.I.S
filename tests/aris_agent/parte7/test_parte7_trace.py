"""Testes do trace JSONL por tarefa em data_dir/traces (Parte 7)."""

from __future__ import annotations

import json

from aris_agent.config import AgentConfig
from aris_agent.contract import Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import ArisAgent
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool


def cfg(tmp_path) -> AgentConfig:
    return AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")


def ferramenta(nome: str, conteudo: str = "ok"):
    spec = ToolSpec(
        name=nome,
        description=f"ferramenta {nome}",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=("teste",),
    )

    @function_tool(spec)
    def _f(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content=conteudo)

    return _f


def montar(tmp_path, script, ferramentas=()):
    registry = ToolRegistry()
    for tool in ferramentas:
        registry.register(tool)
    llm = FakeLLM(script)
    agente = ArisAgent(
        llm, PassthroughExecutor(registry), registry, FakeMemory(), FakeSkills(), cfg(tmp_path)
    )
    return agente, llm


def ler_trace(tmp_path, trace_id):
    caminho = tmp_path / "data" / "traces" / f"{trace_id}.jsonl"
    assert caminho.is_file(), f"trace {caminho} nao existe"
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    return [json.loads(linha) for linha in linhas]


def test_trace_contem_a_tarefa(tmp_path) -> None:
    agente, _ = montar(
        tmp_path,
        [
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(id="c1", name="ferramenta_a", arguments={"x": 1})],
            ),
            ChatMessage(role="assistant", content="terminado"),
        ],
        [ferramenta("ferramenta_a")],
    )
    res = agente.run("faz a operacao com x", "s1", AutoConfirm(True))
    registros = ler_trace(tmp_path, res.trace_id)

    eventos = [r["evento"] for r in registros]
    assert eventos[0] == "start"
    assert "llm" in eventos and "tool_call" in eventos and "tool" in eventos
    assert eventos[-1] == "final"

    start = registros[0]
    assert start["session_id"] == "s1"
    assert start["user_text"] == "faz a operacao com x"

    chamada_llm = next(r for r in registros if r["evento"] == "llm" and "passo" in r)
    assert chamada_llm["passo"] == 1
    assert chamada_llm["dificuldade"] in ("easy", "normal", "hard")
    assert chamada_llm["tokens_prompt"] > 0

    ferramenta_reg = next(r for r in registros if r["evento"] == "tool")
    assert ferramenta_reg["nome"] == "ferramenta_a"
    assert ferramenta_reg["ok"] is True
    assert "ms" in ferramenta_reg

    final = registros[-1]
    assert final["motivo"] == "done"
    assert final["texto"] == res.text
    assert final["passos"] == res.steps
    assert final["chamadas"] == res.tool_calls
    assert final["tokens_prompt"] == res.usage.prompt_tokens


def test_trace_registra_mensagens(tmp_path) -> None:
    agente, _ = montar(tmp_path, [ChatMessage(role="assistant", content="resposta")])
    res = agente.run("oi chefe", "s1", AutoConfirm(True))
    registros = ler_trace(tmp_path, res.trace_id)

    messages = next(r for r in registros if r["evento"] == "messages")
    papeis = [m["role"] for m in messages["mensagens"]]
    assert papeis == ["system", "user", "assistant"]


def test_trace_sem_segredos(tmp_path) -> None:
    agente, _ = montar(
        tmp_path,
        [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="ferramenta_a",
                        arguments={"chave": "gsk_abcdef12345678"},
                    )
                ],
            ),
            ChatMessage(role="assistant", content="ok"),
        ],
        [ferramenta("ferramenta_a")],
    )
    texto_user = "usa a chave gsk_abcdef12345678 no servidor"
    res = agente.run(texto_user, "s1", AutoConfirm(True))

    caminho = tmp_path / "data" / "traces" / f"{res.trace_id}.jsonl"
    bruto = caminho.read_text(encoding="utf-8")
    assert "gsk_abcdef12345678" not in bruto
    assert "[REDACTED]" in bruto


def test_trace_de_parada_por_limite(tmp_path) -> None:
    config = AgentConfig(
        workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data", max_steps=1
    )
    registry = ToolRegistry()
    registry.register(ferramenta("ferramenta_a"))
    llm = FakeLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(id="c1", name="ferramenta_a", arguments={})],
            ),
            ChatMessage(role="assistant", content="tarde"),
        ]
    )
    agente = ArisAgent(
        llm, PassthroughExecutor(registry), registry, FakeMemory(), FakeSkills(), config
    )
    res = agente.run("faz muita coisa", "s1", AutoConfirm(True))
    registros = ler_trace(tmp_path, res.trace_id)

    final = registros[-1]
    assert final["evento"] == "final"
    assert final["motivo"] == "max_steps"
    assert "limite de etapas" in final["texto"]


def test_trace_de_tarefa_cancelada(tmp_path) -> None:
    agente, _ = montar(tmp_path, [ChatMessage(role="assistant", content="nunca")])
    agente.cancel("s1")
    res = agente.run("oi", "s1", AutoConfirm(True))
    registros = ler_trace(tmp_path, res.trace_id)

    assert registros[-1]["motivo"] == "cancelled"
    assert registros[0]["evento"] == "start"


def test_trace_id_diferentes_por_tarefa(tmp_path) -> None:
    agente, _ = montar(
        tmp_path,
        [ChatMessage(role="assistant", content="um"), ChatMessage(role="assistant", content="dois")],
    )
    res1 = agente.run("oi", "s1", AutoConfirm(True))
    res2 = agente.run("oi", "s1", AutoConfirm(True))

    assert res1.trace_id != res2.trace_id
    assert (tmp_path / "data" / "traces" / f"{res1.trace_id}.jsonl").is_file()
    assert (tmp_path / "data" / "traces" / f"{res2.trace_id}.jsonl").is_file()
