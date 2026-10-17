"""Testes do plano leve e da ferramenta interna plan_update (Parte 7)."""

from __future__ import annotations

import threading

from aris_agent.config import AgentConfig
from aris_agent.contract import Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import PLAN_SPEC, ArisAgent, PlanState, make_plan_tool, validate_args
from aris_agent.core.state import Emitter, TaskState
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool

ITENS = [
    {"text": "estudar logica", "status": "doing"},
    {"text": "fazer exercicios", "status": "todo"},
    {"text": "revisar erros", "status": "todo"},
]


def cfg(tmp_path) -> AgentConfig:
    return AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")


def montar(tmp_path, script):
    registry = ToolRegistry()
    llm = FakeLLM(script)
    executor = PassthroughExecutor(registry)
    agente = ArisAgent(
        llm, executor, registry, FakeMemory(), FakeSkills(), cfg(tmp_path)
    )
    return agente, llm, executor


def chamada(nome: str, args: dict, id_: str = "c1") -> ChatMessage:
    return ChatMessage(role="assistant", tool_calls=[ToolCall(id=id_, name=nome, arguments=args)])


def fim(texto: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=texto)


class Eventos:
    def __init__(self) -> None:
        self.tipos: list[str] = []
        self.eventos: list = []

    def __call__(self, evento) -> None:
        self.tipos.append(evento.type)
        self.eventos.append(evento)


def test_plan_update_passa_pelo_executor(tmp_path) -> None:
    agente, llm, executor = montar(tmp_path, [chamada("plan_update", {"items": ITENS}), fim("plano pronto")])
    eventos = Eventos()
    res = agente.run(
        "monta um plano de 3 etapas para estudar python hoje",
        "s1",
        AutoConfirm(True),
        eventos,
    )

    assert res.ok and res.tool_calls == 1
    assert executor.calls[0].name == "plan_update"  # sempre via ToolExecutor
    assert executor.calls[0].arguments["items"][0]["text"] == "estudar logica"
    assert eventos.tipos == ["tool_call", "plan", "tool_result", "final"]


def test_plano_entra_no_prompt_seguinte(tmp_path) -> None:
    agente, llm, _ = montar(tmp_path, [chamada("plan_update", {"items": ITENS}), fim("plano pronto")])
    agente.run("monta um plano de 3 etapas para estudar python hoje", "s1", AutoConfirm(True))

    prompt = llm.calls[1]["messages"][0].content
    assert "Plano atual da tarefa" in prompt
    assert "estudar logica" in prompt
    assert "[em andamento] estudar logica" in prompt
    assert "[pendente] fazer exercicios" in prompt
    # plano com 3+ etapas muda a dificuldade para hard
    assert llm.calls[1]["difficulty"] == "hard"


def test_evento_de_plano_carrega_os_itens(tmp_path) -> None:
    agente, _, _ = montar(tmp_path, [chamada("plan_update", {"items": ITENS}), fim("ok")])
    eventos = Eventos()
    agente.run("monta um plano de 3 etapas para estudar python hoje", "s1", AutoConfirm(True), eventos)

    plano = next(e for e in eventos.eventos if e.type == "plan")
    assert [i["text"] for i in plano.data["items"]] == [
        "estudar logica",
        "fazer exercicios",
        "revisar erros",
    ]
    assert plano.data["version"] == 1


def test_plano_atualizado_de_novo(tmp_path) -> None:
    itens2 = [dict(ITENS[0], status="done"), dict(ITENS[1], status="doing"), ITENS[2]]
    agente, _, _ = montar(
        tmp_path,
        [chamada("plan_update", {"items": ITENS}, "c1"), chamada("plan_update", {"items": itens2}, "c2"), fim("ok")],
    )
    eventos = Eventos()
    agente.run("monta um plano de 3 etapas para estudar python hoje", "s1", AutoConfirm(True), eventos)

    planos = [e for e in eventos.eventos if e.type == "plan"]
    assert len(planos) == 2
    assert planos[0].data["version"] == 1 and planos[1].data["version"] == 2
    assert planos[1].data["items"][0]["status"] == "done"


def test_plan_update_sem_tarefa_ativa(tmp_path) -> None:
    tool = make_plan_tool(lambda _sid: None)
    ctx = ToolContext(
        session_id="s1",
        workdir=tmp_path,
        config=cfg(tmp_path),
        cancel=threading.Event(),
    )
    resultado = tool.run({"items": ITENS}, ctx)
    assert resultado.ok is False
    assert "tarefa ativa" in (resultado.error or "")


def test_plan_update_com_estado_inativo(tmp_path) -> None:
    estado = TaskState(
        session_id="s1",
        trace_id="t",
        cancel=threading.Event(),
        plan=PlanState(),
        emitter=Emitter(None),
    )
    estado.active = False
    tool = make_plan_tool(lambda _sid: estado)
    ctx = ToolContext(
        session_id="s1",
        workdir=tmp_path,
        config=cfg(tmp_path),
        cancel=threading.Event(),
    )
    resultado = tool.run({"items": ITENS}, ctx)
    assert resultado.ok is False


def test_schema_do_plan_update_rejeita_status_ruim() -> None:
    erro = validate_args(PLAN_SPEC, {"items": [{"text": "a", "status": "banana"}]})
    assert erro is not None and "valor inválido" in erro


def test_schema_do_plan_update_rejeita_item_sem_texto() -> None:
    erro = validate_args(PLAN_SPEC, {"items": [{"status": "todo"}]})
    assert erro is not None and "obrigatório" in erro


def test_schema_do_plan_update_rejeita_sem_items() -> None:
    erro = validate_args(PLAN_SPEC, {})
    assert erro is not None and "items" in erro


def test_plan_state_texto_e_lista() -> None:
    plano = PlanState()
    assert plano.as_text() == ""
    plano.set(ITENS)
    assert plano.version == 1
    assert len(plano.as_list()) == 3
    assert "[em andamento] estudar logica" in plano.as_text()
    plano.set([{"text": "unica", "status": "done"}])
    assert plano.version == 2
    assert plano.as_list() == [{"text": "unica", "status": "done"}]


def test_spec_do_plan_update_e_read() -> None:
    assert PLAN_SPEC.name == "plan_update"
    assert PLAN_SPEC.risk == Risk.READ
    assert "plano" in PLAN_SPEC.tags
    assert PLAN_SPEC.parameters["required"] == ["items"]


def test_registro_existente_nao_quebra(tmp_path) -> None:
    """Um registro pré-existente de plan_update não derruba a criação do agente."""
    registry = ToolRegistry()

    def plano_valido(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content="feito")

    spec = ToolSpec(
        name="plan_update",
        description="ja existe",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
    )
    registry.register(function_tool(spec)(plano_valido))
    llm = FakeLLM([fim("ok")])
    agente = ArisAgent(
        llm,
        PassthroughExecutor(registry),
        registry,
        FakeMemory(),
        FakeSkills(),
        cfg(tmp_path),
    )
    res = agente.run("oi chefe", "s1", AutoConfirm(True))
    assert res.ok
