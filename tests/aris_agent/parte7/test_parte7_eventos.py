"""Testes dos eventos do laço (Parte 7): ordem, confirmação, redação e falhas."""

from __future__ import annotations

import json

from aris_agent.config import AgentConfig
from aris_agent.contract import ConfirmRequest, Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import ArisAgent
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool


def cfg(tmp_path, **kwargs) -> AgentConfig:
    return AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data", **kwargs)


def ferramenta(nome: str, conteudo: str = "ok"):
    spec = ToolSpec(
        name=nome,
        description=f"ferramenta {nome} de teste",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=("teste",),
    )

    @function_tool(spec)
    def _f(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content=conteudo)

    return _f


def chamada(nome: str, args: dict, id_: str = "c1") -> ChatMessage:
    return ChatMessage(role="assistant", tool_calls=[ToolCall(id=id_, name=nome, arguments=args)])


class Eventos:
    def __init__(self) -> None:
        self.tipos: list[str] = []
        self.eventos: list = []

    def __call__(self, evento) -> None:
        self.tipos.append(evento.type)
        self.eventos.append(evento)

    def do(self, tipo: str):
        return next(e for e in self.eventos if e.type == tipo)


class ExecutorComConfirmacao(PassthroughExecutor):
    """Pede confirmação ao usuário antes de rodar (a Parte 5 fará isso de verdade)."""

    def execute(self, call, ctx, confirm=None):
        pedido = ConfirmRequest(
            tool_name=call.name,
            args_preview=str(call.arguments),
            risk=Risk.READ,
            reason="teste de confirmacao",
        )
        if confirm is not None and not confirm(pedido):
            return ToolResult(ok=False, error="usuario recusou")
        return super().execute(call, ctx, confirm)


def montar(tmp_path, script, ferramentas=(), executor_cls=PassthroughExecutor):
    registry = ToolRegistry()
    for tool in ferramentas:
        registry.register(tool)
    llm = FakeLLM(script)
    executor = executor_cls(registry)
    agente = ArisAgent(llm, executor, registry, FakeMemory(), FakeSkills(), cfg(tmp_path))
    return agente, llm, executor


def test_eventos_de_ferramenta_na_ordem(tmp_path) -> None:
    agente, _, _ = montar(
        tmp_path,
        [chamada("ferramenta_a", {}, "c1"), ChatMessage(role="assistant", content="feito")],
        [ferramenta("ferramenta_a")],
    )
    eventos = Eventos()
    agente.run("executa a operação", "s1", AutoConfirm(True), eventos)
    assert eventos.tipos == ["tool_call", "tool_result", "final"]


def test_evento_de_confirmacao(tmp_path) -> None:
    auto = AutoConfirm(True)
    agente, _, executor = montar(
        tmp_path,
        [chamada("ferramenta_a", {}, "c1"), ChatMessage(role="assistant", content="rodou")],
        [ferramenta("ferramenta_a")],
        executor_cls=ExecutorComConfirmacao,
    )
    eventos = Eventos()
    res = agente.run("executa a operação", "s1", auto, eventos)

    assert res.ok
    assert auto.requests and auto.requests[0].tool_name == "ferramenta_a"
    assert eventos.tipos == ["tool_call", "confirm", "tool_result", "final"]
    confirm = eventos.do("confirm")
    assert confirm.data["approved"] is True
    assert confirm.data["risk"] == "READ"
    assert confirm.data["tool_name"] == "ferramenta_a"


def test_confirmacao_recusada(tmp_path) -> None:
    auto = AutoConfirm(False)
    agente, llm, _ = montar(
        tmp_path,
        [chamada("ferramenta_a", {}, "c1"), ChatMessage(role="assistant", content="sem problemas")],
        [ferramenta("ferramenta_a")],
        executor_cls=ExecutorComConfirmacao,
    )
    eventos = Eventos()
    res = agente.run("executa a operação", "s1", auto, eventos)

    assert res.ok
    assert eventos.do("confirm").data["approved"] is False
    # a recusa volta como erro de ferramenta para o modelo
    assert "recusou" in llm.calls[1]["messages"][-1].content


def test_eventos_sem_segredos(tmp_path) -> None:
    agente, _, _ = montar(
        tmp_path,
        [chamada("vaza", {}, "c1"), ChatMessage(role="assistant", content="ok")],
        [ferramenta("vaza", conteudo="chave gsk_abc123456789 liberada")],
    )
    eventos = Eventos()
    agente.run("usa a chave gsk_abc123456789", "s1", AutoConfirm(True), eventos)

    bruto = json.dumps(
        [e.data for e in eventos.eventos], ensure_ascii=False, default=str
    )
    assert "gsk_abc123456789" not in bruto
    assert "[REDACTED]" in bruto
    tool_result = eventos.do("tool_result")
    assert "gsk_" not in json.dumps(tool_result.data, ensure_ascii=False)


def test_sink_que_bruta_nao_derruba_o_laço(tmp_path) -> None:
    agente, _, _ = montar(
        tmp_path, [ChatMessage(role="assistant", content="seguimos")]
    )

    def quebra(evento) -> None:
        raise RuntimeError("ui")

    res = agente.run("oi chefe", "s1", AutoConfirm(True), quebra)
    assert res.ok and res.text == "seguimos"


def test_falha_de_provedor_emite_error_e_final(tmp_path) -> None:
    agente, _, _ = montar(tmp_path, [])  # roteiro vazio: FakeLLM levanta ProviderError
    eventos = Eventos()
    res = agente.run("qualquer coisa", "s1", AutoConfirm(True), eventos)

    assert res.ok is False and res.stopped_reason == "error"
    assert eventos.tipos == ["error", "final"]
    assert "modelo" in res.text
    assert res.usage.prompt_tokens == 0


def test_evento_final_bate_com_o_resultado(tmp_path) -> None:
    agente, _, _ = montar(tmp_path, [ChatMessage(role="assistant", content="resposta curta")])
    eventos = Eventos()
    res = agente.run("oi", "s1", AutoConfirm(True), eventos)

    final = eventos.do("final")
    assert final.data["text"] == res.text
    assert final.data["stopped_reason"] == res.stopped_reason
    assert final.data["trace_id"] == res.trace_id
    assert final.data["steps"] == res.steps
    assert final.data["tool_calls"] == res.tool_calls
