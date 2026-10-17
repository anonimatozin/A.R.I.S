"""Testes do laço do agente (Parte 7): conversa, ferramentas, limites, laço, cancelamento."""

from __future__ import annotations

from aris_agent.config import AgentConfig
from aris_agent.contract import Agent, Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import ArisAgent
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool

# ----------------------------------------------------------------- apoio


def cfg(tmp_path, **kwargs) -> AgentConfig:
    return AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data", **kwargs)


def ferramenta(nome: str, conteudo: str = "ok", descricao: str | None = None, params=None):
    spec = ToolSpec(
        name=nome,
        description=descricao or f"ferramenta {nome} de teste",
        parameters=params or {"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=("teste",),
    )

    @function_tool(spec)
    def _f(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content=conteudo)

    return _f


def chamada(nome: str, args: dict, id_: str = "c1") -> ChatMessage:
    return ChatMessage(role="assistant", tool_calls=[ToolCall(id=id_, name=nome, arguments=args)])


def fim(texto: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=texto)


def montar(tmp_path, script, ferramentas=(), config=None, memoria=None, skills=None, llm=None):
    registry = ToolRegistry()
    for tool in ferramentas:
        registry.register(tool)
    fake_llm = llm or FakeLLM(script)
    memoria = memoria or FakeMemory()
    executor = PassthroughExecutor(registry)
    agente = ArisAgent(
        fake_llm, executor, registry, memoria, skills or FakeSkills(), config or cfg(tmp_path)
    )
    return agente, fake_llm, executor, memoria


class Eventos:
    """Coleta os AgentEvent emitidos durante um run."""

    def __init__(self) -> None:
        self.tipos: list[str] = []
        self.eventos: list = []

    def __call__(self, evento) -> None:
        self.tipos.append(evento.type)
        self.eventos.append(evento)


# ----------------------------------------------------------------- testes


def test_conversa_sem_ferramentas(tmp_path) -> None:
    agente, llm, executor, _ = montar(
        tmp_path, [fim("Oi, chefe! Em que posso ajudar?")], [ferramenta("pesquisa_web")]
    )
    eventos = Eventos()
    res = agente.run("oi, tudo bem?", "s1", AutoConfirm(True), eventos)

    assert res.ok and res.stopped_reason == "done"
    assert res.text == "Oi, chefe! Em que posso ajudar?"
    assert res.steps == 1 and res.tool_calls == 0
    assert res.trace_id and len(res.trace_id) == 16
    assert executor.calls == []
    assert len(llm.calls) == 1
    assert llm.calls[0]["difficulty"] == "easy"
    # só o núcleo (plan_update) foi enviado: a ferramenta do pedido não foi escolhida
    assert {s.name for s in llm.calls[0]["tools"]} == {"plan_update"}
    assert eventos.tipos == ["final"]


def test_duas_ferramentas_encadeadas(tmp_path) -> None:
    agente, llm, executor, _ = montar(
        tmp_path,
        [chamada("ferramenta_a", {}, "c1"), chamada("ferramenta_b", {}, "c2"), fim("pronto, chefe.")],
        [ferramenta("ferramenta_a"), ferramenta("ferramenta_b")],
    )
    eventos = Eventos()
    res = agente.run("prepara os dois arquivos agora", "s1", AutoConfirm(True), eventos)

    assert res.ok and res.stopped_reason == "done"
    assert res.text == "pronto, chefe."
    assert res.steps == 3 and res.tool_calls == 2
    assert [c.name for c in executor.calls] == ["ferramenta_a", "ferramenta_b"]
    assert eventos.tipos == ["tool_call", "tool_result", "tool_call", "tool_result", "final"]

    # chamada 2: system, user, assistant(tool_calls), tool
    segundas = llm.calls[1]["messages"]
    assert [m.role for m in segundas] == ["system", "user", "assistant", "tool"]
    assert segundas[-1].content == "ok" and segundas[-1].tool_call_id == "c1"
    # a ferramenta já usada volta a ser enviada
    assert {s.name for s in llm.calls[1]["tools"]} >= {"ferramenta_a"}
    # chamada 3: as duas respostas estão no histórico
    terceiras = llm.calls[2]["messages"]
    assert [m.role for m in terceiras] == [
        "system", "user", "assistant", "tool", "assistant", "tool"
    ]
    assert terceiras[-1].tool_call_id == "c2"


def test_ferramenta_inexistente_vai_erro_para_o_llm(tmp_path) -> None:
    agente, llm, executor, _ = montar(
        tmp_path, [chamada("nao_existe", {}, "c1"), fim("desculpa, chefe, não achei a ferramenta.")]
    )
    res = agente.run("faz a operação especial", "s1", AutoConfirm(True))

    assert res.ok and res.tool_calls == 1
    assert executor.calls == []  # nunca chegou ao executor
    tool_msg = llm.calls[1]["messages"][-1]
    assert tool_msg.role == "tool"
    assert "inexistente" in tool_msg.content
    assert "nao_existe" in tool_msg.content


def test_argumentos_invalidos_corrigem(tmp_path) -> None:
    params = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    agente, llm, executor, _ = montar(
        tmp_path,
        [chamada("ferramenta_x", {}, "c1"), fim("agora sim, chefe.")],
        [ferramenta("ferramenta_x", params=params)],
    )
    res = agente.run("roda a ferramenta x com o valor", "s1", AutoConfirm(True))

    assert res.ok and res.tool_calls == 1
    assert executor.calls == []  # argumento ruim não passa pelo executor
    tool_msg = llm.calls[1]["messages"][-1]
    assert tool_msg.role == "tool"
    assert "obrigatório" in tool_msg.content
    assert "ferramenta_x" in tool_msg.content


def test_argumento_de_tipo_errado(tmp_path) -> None:
    params = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    agente, llm, _, _ = montar(
        tmp_path,
        [chamada("ferramenta_x", {"x": 42}, "c1"), fim("corrigido")],
        [ferramenta("ferramenta_x", params=params)],
    )
    agente.run("roda a ferramenta x", "s1", AutoConfirm(True))
    tool_msg = llm.calls[1]["messages"][-1]
    assert "esperado string" in tool_msg.content


def test_tres_argumentos_invalidos_param(tmp_path) -> None:
    params = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    agente, llm, _, _ = montar(
        tmp_path,
        [
            chamada("ferramenta_x", {}, "c1"),
            chamada("ferramenta_x", {"x": 1}, "c2"),
            chamada("ferramenta_x", {"y": "z"}, "c3"),
        ],
        [ferramenta("ferramenta_x", params=params)],
    )
    res = agente.run("roda a ferramenta x direito", "s1", AutoConfirm(True))

    assert res.ok is False and res.stopped_reason == "error"
    assert len(llm.calls) == 3  # duas correções; na terceira, parou
    assert "invalidos" in res.text or "continuaram" in res.text


def test_estouro_de_max_steps(tmp_path) -> None:
    config = cfg(tmp_path, max_steps=2)
    agente, llm, executor, _ = montar(
        tmp_path,
        [chamada("ferramenta_a", {}, "c1"), chamada("ferramenta_a", {}, "c2"), fim("tarde demais")],
        [ferramenta("ferramenta_a")],
        config=config,
    )
    eventos = Eventos()
    res = agente.run("faz um monte de coisas", "s1", AutoConfirm(True), eventos)

    assert res.ok is False and res.stopped_reason == "max_steps"
    assert res.steps == 2 and res.tool_calls == 2
    assert len(llm.calls) == 2  # a terceira chamada nunca aconteceu
    assert "limite de etapas" in res.text
    assert "ferramenta_a" in res.text  # diz o que foi feito
    assert "inventar" in res.text
    assert eventos.tipos[-1] == "final"
    assert eventos.eventos[-1].data["stopped_reason"] == "max_steps"


def test_estouro_de_orcamento(tmp_path) -> None:
    config = cfg(tmp_path, max_total_tokens_per_task=10)
    agente, llm, _, _ = montar(
        tmp_path,
        [chamada("ferramenta_a", {}, "c1"), fim("nunca chega")],
        [ferramenta("ferramenta_a")],
        config=config,
    )
    res = agente.run("faz a operação longa", "s1", AutoConfirm(True))

    assert res.ok is False and res.stopped_reason == "budget"
    assert len(llm.calls) == 1  # parou antes da segunda chamada
    assert res.tool_calls == 1
    assert "orcamento" in res.text
    assert res.usage.prompt_tokens + res.usage.completion_tokens > 10


def test_cancelamento_durante_a_tarefa(tmp_path) -> None:
    spec = ToolSpec(
        name="para_ai",
        description="para tudo no meio",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=("teste",),
    )

    @function_tool(spec)
    def para_ai(args: dict, ctx: ToolContext) -> ToolResult:
        ctx.cancel.set()
        return ToolResult(ok=True, content="parado")

    agente, llm, _, _ = montar(
        tmp_path, [chamada("para_ai", {}, "c1"), fim("nunca chega")], [para_ai]
    )
    res = agente.run("executa a parada", "s1", AutoConfirm(True))

    assert res.ok is False and res.stopped_reason == "cancelled"
    assert len(llm.calls) == 1
    assert "cancelada" in res.text


def test_cancelamento_antes_de_comecar(tmp_path) -> None:
    agente, llm, executor, _ = montar(
        tmp_path, [fim("nunca chega")], [ferramenta("ferramenta_a")]
    )
    agente.cancel("s1")
    res = agente.run("faz qualquer coisa", "s1", AutoConfirm(True))

    assert res.ok is False and res.stopped_reason == "cancelled"
    assert len(llm.calls) == 0 and executor.calls == []
    assert res.steps == 0 and res.tool_calls == 0
    assert "cancelada" in res.text


def test_deteccao_de_laco(tmp_path) -> None:
    agente, llm, executor, _ = montar(
        tmp_path,
        [
            chamada("ferramenta_a", {}, "c1"),
            chamada("ferramenta_a", {}, "c2"),
            chamada("ferramenta_a", {}, "c3"),
        ],
        [ferramenta("ferramenta_a")],
    )
    res = agente.run("repete a operação até dar certo", "s1", AutoConfirm(True))

    assert res.ok is False and res.stopped_reason == "error"
    assert len(llm.calls) == 3
    assert len(executor.calls) == 2  # a terceira repetição não executou
    assert "repetindo" in res.text


def test_atende_ao_protocolo_agent(tmp_path) -> None:
    agente, _, _, _ = montar(tmp_path, [fim("oi")])
    assert isinstance(agente, Agent)


def test_executor_que_lanca_excecao_nao_derruba(tmp_path) -> None:
    class ExecutorRuim:
        def execute(self, call, ctx, confirm):
            raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(ferramenta("qualquer"))
    llm = FakeLLM([chamada("qualquer", {}, "c1"), fim("seguimos")])
    agente = ArisAgent(llm, ExecutorRuim(), registry, FakeMemory(), FakeSkills(), cfg(tmp_path))
    res = agente.run("tenta aí", "s1", AutoConfirm(True))

    assert res.ok and res.text == "seguimos"
    # a mensagem de erro da ferramenta foi devolvida ao modelo
    assert "RuntimeError: boom" in llm.calls[1]["messages"][-1].content


def test_dois_agentes_no_mesmo_registry(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ferramenta("ferramenta_a"))
    llm1 = FakeLLM([fim("um")])
    llm2 = FakeLLM([fim("dois")])
    agente1 = ArisAgent(llm1, PassthroughExecutor(registry), registry, FakeMemory(), FakeSkills(), cfg(tmp_path))
    agente2 = ArisAgent(llm2, PassthroughExecutor(registry), registry, FakeMemory(), FakeSkills(), cfg(tmp_path))
    assert agente1.run("oi", "s1", AutoConfirm(True)).text == "um"
    assert agente2.run("oi", "s2", AutoConfirm(True)).text == "dois"


def test_sessao_repetida_reusa_o_estado(tmp_path) -> None:
    agente, _, _, memoria = montar(tmp_path, [fim("primeira"), fim("segunda")])
    agente.run("primeiro pedido", "s1", AutoConfirm(True))
    res2 = agente.run("segundo pedido", "s1", AutoConfirm(True))
    assert res2.ok and res2.text == "segunda"
    turnos = memoria.recent_turns("s1", 10)
    assert [t.role for t in turnos] == ["user", "assistant", "user", "assistant"]
