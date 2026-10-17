"""Testes da resposta de voz: prompt curto, truncamento de ferramentas (Parte 7)."""

from __future__ import annotations

from aris_agent.config import AgentConfig
from aris_agent.contract import Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import ArisAgent, PromptBuilder
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool


def montar(tmp_path, script, ferramentas=(), config=None):
    registry = ToolRegistry()
    for tool in ferramentas:
        registry.register(tool)
    llm = FakeLLM(script)
    agente = ArisAgent(
        llm,
        PassthroughExecutor(registry),
        registry,
        FakeMemory(),
        FakeSkills(),
        config
        or AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data"),
    )
    return agente, llm


def ferramenta_larga(nome: str, tamanho: int):
    spec = ToolSpec(
        name=nome,
        description=f"ferramenta {nome} que devolve texto enorme",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=("teste",),
    )

    @function_tool(spec)
    def _f(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content="x" * tamanho)

    return _f


def test_prompt_manda_responder_curto_para_voz(tmp_path) -> None:
    texto = PromptBuilder().build("faz um relatorio", workspace="C:/ws")
    assert "1 a 3 frases" in texto
    assert "salve em arquivo no workspace" in texto
    assert "C:/ws" in texto
    assert "voz alta" in texto
    assert "curtas, naturais e diretas" in texto


def test_resultado_longo_e_truncado_no_historico(tmp_path) -> None:
    config = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        max_tool_chars=120,
    )
    agente, llm = montar(
        tmp_path,
        [
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(id="c1", name="gigante", arguments={})],
            ),
            ChatMessage(role="assistant", content="resumo curto"),
        ],
        [ferramenta_larga("gigante", 5000)],
        config=config,
    )
    res = agente.run("monta o relatorio completo", "s1", AutoConfirm(True))

    assert res.ok and res.text == "resumo curto"
    tool_msg = llm.calls[1]["messages"][-1]
    assert tool_msg.role == "tool"
    assert len(tool_msg.content) <= 120
    assert "caracteres omitidos" in tool_msg.content


def test_resposta_final_curta_passa_intacta(tmp_path) -> None:
    texto_curto = "Sim, chefe, esta feito."
    agente, _ = montar(tmp_path, [ChatMessage(role="assistant", content=texto_curto)])
    eventos = []
    res = agente.run("confirma la", "s1", AutoConfirm(True), eventos.append)

    assert res.text == texto_curto
    assert res.ok
    final = next(e for e in eventos if e.type == "final")
    assert final.data["text"] == texto_curto


def test_erro_de_ferramenta_fica_curto_no_historico(tmp_path) -> None:
    spec = ToolSpec(
        name="falha",
        description="sempre falha",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=("teste",),
    )

    @function_tool(spec)
    def falha(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=False, error="arquivo nao encontrado: " + "y" * 900)

    agente, llm = montar(
        tmp_path,
        [
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(id="c1", name="falha", arguments={})],
            ),
            ChatMessage(role="assistant", content="nao achei o arquivo"),
        ],
        [falha],
    )
    res = agente.run("le o arquivo de dados", "s1", AutoConfirm(True))

    assert res.ok
    tool_msg = llm.calls[1]["messages"][-1]
    assert tool_msg.role == "tool"
    assert "arquivo nao encontrado" in tool_msg.content
    assert len(tool_msg.content) <= 8000
