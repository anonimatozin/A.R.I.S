"""Testes da passada única de verificação do resultado (Parte 7)."""

from __future__ import annotations

from aris_agent.config import AgentConfig
from aris_agent.contract import Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import ArisAgent
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool


def cfg(tmp_path) -> AgentConfig:
    return AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")


def ferramenta(nome: str):
    spec = ToolSpec(
        name=nome,
        description=f"ferramenta {nome}",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=("teste",),
    )

    @function_tool(spec)
    def _f(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content="ok")

    return _f


def chamada(nome: str, id_: str) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        tool_calls=[ToolCall(id=id_, name=nome, arguments={})],
    )


def fim(texto: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=texto)


def montar(tmp_path, script, ferramentas=()):
    registry = ToolRegistry()
    for tool in ferramentas:
        registry.register(tool)
    llm = FakeLLM(script)
    agente = ArisAgent(
        llm, PassthroughExecutor(registry), registry, FakeMemory(), FakeSkills(), cfg(tmp_path)
    )
    return agente, llm


def test_verificacao_por_pedido_do_usuario(tmp_path) -> None:
    agente, llm = montar(
        tmp_path,
        [
            chamada("ferramenta_a", "c1"),
            fim("o resultado esta 42 e pronto"),
            fim("o resultado esta 42, chefe, conferido"),
        ],
        [ferramenta("ferramenta_a")],
    )
    res = agente.run("confira se o resultado esta certo", "s1", AutoConfirm(True))

    assert res.ok
    assert res.text == "o resultado esta 42, chefe, conferido"
    assert len(llm.calls) == 3  # uma única passada de verificação
    assert llm.calls[2]["difficulty"] == "easy"
    assert llm.calls[2]["tools"] == []

    verificacao = llm.calls[2]["messages"][-1]
    assert "CONFERENCIA FINAL" in verificacao.content
    assert "o resultado esta 42 e pronto" in verificacao.content
    assert "confira se o resultado esta certo" in verificacao.content


def test_verificacao_por_tres_chamadas_de_ferramenta(tmp_path) -> None:
    agente, llm = montar(
        tmp_path,
        [
            chamada("ferramenta_a", "c1"),
            chamada("ferramenta_b", "c2"),
            chamada("ferramenta_c", "c3"),
            fim("resposta original"),
            fim("resposta corrigida"),
        ],
        [ferramenta("ferramenta_a"), ferramenta("ferramenta_b"), ferramenta("ferramenta_c")],
    )
    res = agente.run("faz as tres operacoes", "s1", AutoConfirm(True))

    assert res.ok
    assert res.tool_calls == 3
    assert res.text == "resposta corrigida"
    assert len(llm.calls) == 5  # 4 do laço + 1 de verificação
    assert llm.calls[4]["difficulty"] == "easy"


def test_sem_verificacao_com_poucas_chamadas(tmp_path) -> None:
    agente, llm = montar(
        tmp_path,
        [
            chamada("ferramenta_a", "c1"),
            chamada("ferramenta_b", "c2"),
            fim("resposta final"),
        ],
        [ferramenta("ferramenta_a"), ferramenta("ferramenta_b")],
    )
    res = agente.run("faz duas operacoes", "s1", AutoConfirm(True))

    assert res.ok and res.text == "resposta final"
    assert len(llm.calls) == 3  # FakeLLM registra antes de falhar: não houve 4ª chamada
    assert llm.remaining == 0


def test_verificacao_que_falha_mantem_o_rascunho(tmp_path) -> None:
    agente, llm = montar(
        tmp_path,
        [chamada("ferramenta_a", "c1"), fim("resposta original boa")],
        [ferramenta("ferramenta_a")],
    )
    res = agente.run("confira se deu certo", "s1", AutoConfirm(True))

    assert res.ok
    assert res.text == "resposta original boa"
    assert len(llm.calls) == 3  # a verificação tentou (e falhou) sem quebrar


def test_verificacao_curta_demais_e_descartada(tmp_path) -> None:
    agente, llm = montar(
        tmp_path,
        [
            chamada("ferramenta_a", "c1"),
            fim("resposta longa e detalhada do pedido inteiro, chefe"),
            fim("sim"),
        ],
        [ferramenta("ferramenta_a")],
    )
    res = agente.run("confira se esta tudo certo", "s1", AutoConfirm(True))

    assert res.ok
    assert res.text == "resposta longa e detalhada do pedido inteiro, chefe"
