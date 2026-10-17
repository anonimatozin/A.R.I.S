"""Testes do ContextManager: orçamento de tokens e compactação do histórico (Parte 7)."""

from __future__ import annotations

from aris_agent.config import AgentConfig
from aris_agent.contract import Risk, ToolCall, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import ArisAgent, ContextManager, estimate_messages, estimate_tokens
from aris_agent.core.prompts import summarize_messages
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool


def sistema(texto: str = "voce e a ARIS") -> ChatMessage:
    return ChatMessage(role="system", content=texto)


def user(texto: str) -> ChatMessage:
    return ChatMessage(role="user", content=texto)


def round_tool(nome: str, id_: str, conteudo: str = "ok") -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[ToolCall(id=id_, name=nome, arguments={})],
        ),
        ChatMessage(role="tool", content=conteudo, tool_call_id=id_, name=nome),
    ]


def valida_tool_pairing(mensagens: list[ChatMessage]) -> None:
    """Nenhuma mensagem tool pode ficar sem a assistant que a pediu."""
    pendentes: set[str] = set()
    for msg in mensagens:
        if msg.role == "assistant" and msg.tool_calls:
            pendentes.update(str(c.id) for c in msg.tool_calls)
        elif msg.role == "tool":
            assert msg.tool_call_id in pendentes, f"tool orfa: {msg.tool_call_id}"
            pendentes.discard(msg.tool_call_id)
        elif msg.role in ("user", "system"):
            pass


def test_estimate() -> None:
    assert estimate_tokens(None) == 0
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcdefgh") == 2
    msgs = [sistema("a" * 40), user("b" * 8)]
    assert estimate_messages(msgs) >= 10 + 2


def test_fit_fora_do_orcamento_devolve_igual() -> None:
    cm = ContextManager(max_tokens=1000)
    msgs = [sistema(), user("oi")]
    assert cm.fit(msgs) == msgs
    assert cm.compacted is False


def test_fit_compacta_com_resumidor() -> None:
    cm = ContextManager(max_tokens=60, keep_recent=2)
    msgs = [sistema("s" * 400), user("pedido"), *round_tool("a", "c1"), *round_tool("b", "c2")]
    chamadas: list[list[ChatMessage]] = []

    def resumidor(mensagens: list[ChatMessage]) -> str:
        chamadas.append(mensagens)
        return "resumo: a e b ja rodaram"

    saida = cm.fit(msgs, resumidor)

    assert len(chamadas) == 1
    assert [m.role for m in saida] == ["system", "user", "user", "assistant", "tool"]
    assert saida[0].content == "s" * 400  # system preservado
    assert saida[1].content == "pedido"  # pedido preservado
    assert saida[2].content == "resumo: a e b ja rodaram"
    assert saida[3].tool_calls and saida[4].tool_call_id == "c2"  # última rodada intacta
    assert cm.compacted is True
    valida_tool_pairing(saida)


def test_fit_compacta_uma_vez_so() -> None:
    cm = ContextManager(max_tokens=60, keep_recent=2)
    msgs = [sistema("s" * 400), user("pedido"), *round_tool("a", "c1"), *round_tool("b", "c2")]
    chamadas: list[object] = []

    def resumidor(mensagens: list[ChatMessage]) -> str:
        chamadas.append(mensagens)
        return "resumo unico"

    primeira = cm.fit(msgs, resumidor)
    segunda = cm.fit(primeira, resumidor)
    assert len(chamadas) == 1  # resumidor só roda uma vez por tarefa
    assert segunda == primeira  # e depois não mexe mais no histórico


def test_fit_sem_resumidor_usa_nota() -> None:
    cm = ContextManager(max_tokens=60, keep_recent=2)
    msgs = [sistema("s" * 400), user("pedido"), *round_tool("a", "c1"), *round_tool("b", "c2")]
    saida = cm.fit(msgs)
    assert saida[2].content.startswith("[historico anterior removido")
    assert "2 mensagens" in saida[2].content
    valida_tool_pairing(saida)


def test_caude_nunca_fica_com_tool_orfa() -> None:
    cm = ContextManager(max_tokens=50, keep_recent=3)
    msgs = [
        sistema("s" * 400),
        user("pedido"),
        *round_tool("a", "c1"),
        *round_tool("b", "c2"),
        *round_tool("c", "c3"),
    ]
    saida = cm.fit(msgs, lambda _m: "resumo geral")
    assert [m.role for m in saida[:3]] == ["system", "user", "user"]
    assert saida[3].role == "assistant" and saida[3].tool_calls
    valida_tool_pairing(saida)


def test_mensagem_de_resumo_truncada() -> None:
    cm = ContextManager(max_tokens=60, keep_recent=2)
    msgs = [sistema("s" * 400), user("p"), *round_tool("a", "c1"), *round_tool("b", "c2")]
    saida = cm.fit(msgs, lambda _m: "r" * 5000)
    assert len(saida[2].content) <= 2000


def test_prompt_de_resumo_pede_objetivo_e_resultados() -> None:
    texto = summarize_messages([sistema("sys"), user("faz a tarefa")])[0].content
    assert "o que ja foi feito" in texto
    assert "o que ainda falta" in texto
    assert "Nao invente" in texto
    assert "faz a tarefa" in texto


# ------------------------------------------------- compactação no laço real


def test_compactacao_dentro_do_laco(tmp_path) -> None:
    config = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        sections={"core": {"max_context_tokens": 300, "keep_recent_messages": 2}},
    )

    def ferramenta(nome: str):
        spec = ToolSpec(
            name=nome,
            description=f"ferramenta {nome}",
            parameters={"type": "object", "properties": {}},
            risk=Risk.READ,
            tags=("teste",),
        )

        @function_tool(spec)
        def _f(args: dict, ctx) -> ToolResult:
            return ToolResult(ok=True, content="ok")

        return _f

    registry = ToolRegistry()
    registry.register(ferramenta("ferramenta_a"))
    registry.register(ferramenta("ferramenta_b"))

    def chamada(nome: str, id_: str) -> ChatMessage:
        return ChatMessage(
            role="assistant",
            tool_calls=[ToolCall(id=id_, name=nome, arguments={})],
        )

    llm = FakeLLM(
        [
            chamada("ferramenta_a", "c1"),
            chamada("ferramenta_b", "c2"),
            ChatMessage(role="assistant", content="resumo do historico ja feito"),
            ChatMessage(role="assistant", content="terminado, chefe"),
        ]
    )
    agente = ArisAgent(
        llm,
        PassthroughExecutor(registry),
        registry,
        FakeMemory(),
        FakeSkills(),
        config,
    )
    res = agente.run("prepara os dois arquivos agora", "s1", AutoConfirm(True))

    assert res.ok and res.text == "terminado, chefe"
    assert len(llm.calls) == 4  # 3 principais + 1 de resumo
    assert llm.calls[2]["difficulty"] == "easy"

    historico = llm.calls[3]["messages"]
    assert len(historico) == 5  # system, pedido, resumo, assistant, tool
    assert historico[0].role == "system"
    assert historico[1].content == "prepara os dois arquivos agora"
    assert historico[2].content == "resumo do historico ja feito"
    assert [m.role for m in historico[3:]] == ["assistant", "tool"]
    valida_tool_pairing(historico)

    # o trace registra a compactação
    trace = (tmp_path / "data" / "traces" / f"{res.trace_id}.jsonl").read_text(
        encoding="utf-8"
    )
    assert "compactado" in trace


def test_resumo_de_contexto_usa_summarize_messages() -> None:
    texto = summarize_messages(
        [ChatMessage(role="assistant", content="ok", tool_calls=[])]
    )[0].content
    assert "modulo de contexto" in texto
    assert "assistant: ok" in texto
