"""Testes de thread-safety: sessões diferentes em paralelo e cancelamento (Parte 7)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from aris_agent.config import AgentConfig
from aris_agent.contract import Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage, LLMResponse, Usage
from aris_agent.core import ArisAgent
from aris_agent.fakes import AutoConfirm, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool

PEDIDOS = 4


class LLMDespachante:
    """LLM determinístico: primeiro planeja com plan_update, depois responde.

    Não usa roteiro compartilhado, então várias threads podem chamá-lo.
    """

    def chat(
        self,
        messages,
        tools=None,
        *,
        difficulty="normal",
        max_tokens=1024,
        temperature=0.3,
    ):
        pedido = next((m.content for m in messages if m.role == "user"), "")
        if any(m.role == "tool" for m in messages):
            mensagem = ChatMessage(role="assistant", content=f"terminado: {pedido}")
            fim = "stop"
        else:
            mensagem = ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="p1",
                        name="plan_update",
                        arguments={"items": [{"text": pedido, "status": "done"}]},
                    )
                ],
            )
            fim = "tool_calls"
        return LLMResponse(
            message=mensagem,
            usage=Usage(prompt_tokens=10, completion_tokens=5),
            provider="teste",
            model="teste",
            finish_reason=fim,
        )


def montar(tmp_path):
    registry = ToolRegistry()
    memoria = FakeMemory()
    agente = ArisAgent(
        LLMDespachante(),
        PassthroughExecutor(registry),
        registry,
        memoria,
        FakeSkills(),
        AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data"),
    )
    return agente, memoria


def test_sessoes_diferentes_rodam_em_paralelo(tmp_path) -> None:
    agente, _ = montar(tmp_path)

    def tarefa(indice: int):
        eventos: list = []
        res = agente.run(
            f"tarefa da sessao {indice}",
            f"s{indice}",
            AutoConfirm(True),
            eventos.append,
        )
        return res, eventos

    with ThreadPoolExecutor(max_workers=PEDIDOS) as pool:
        saidas = list(pool.map(tarefa, range(PEDIDOS)))

    for indice, (res, eventos) in enumerate(saidas):
        assert res.ok and res.stopped_reason == "done", res
        assert res.text == f"terminado: tarefa da sessao {indice}"
        plano = next(e for e in eventos if e.type == "plan")
        assert plano.data["items"][0]["text"] == f"tarefa da sessao {indice}"

    # cada sessão teve o seu próprio plano (sem cruzamento de estado)
    textos = {
        e.data["items"][0]["text"]
        for _, eventos in saidas
        for e in eventos
        if e.type == "plan"
    }
    assert len(textos) == PEDIDOS


def test_mesma_sessao_e_serializada(tmp_path) -> None:
    agente, memoria = montar(tmp_path)

    def tarefa(indice: int):
        return agente.run(f"pedido {indice}", "mesma", AutoConfirm(True))

    with ThreadPoolExecutor(max_workers=4) as pool:
        resultados = list(pool.map(tarefa, range(4)))

    assert all(res.ok for res in resultados)
    assert [res.stopped_reason for res in resultados] == ["done"] * 4
    assert len({res.trace_id for res in resultados}) == 4
    # 4 execuções completas = 8 turnos (user + assistant por tarefa)
    assert len(memoria.recent_turns("mesma", 50)) == 8


def test_cancel_vindo_de_outra_thread(tmp_path) -> None:
    """A ferramenta pausa; outra thread cancela; o laço para sem nova chamada ao LLM."""
    registry = ToolRegistry()
    iniciou = threading.Event()
    liberar = threading.Event()

    spec = ToolSpec(
        name="lenta",
        description="ferramenta que espera ser liberada",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=("teste",),
    )

    @function_tool(spec)
    def lenta(args: dict, ctx: ToolContext) -> ToolResult:
        iniciou.set()
        liberar.wait(timeout=10)
        return ToolResult(ok=True, content="quase")

    registry.register(lenta)

    class LLMDuas:
        def __init__(self) -> None:
            self.chamadas = 0

        def chat(
            self, messages, tools=None, *, difficulty="normal", max_tokens=1024, temperature=0.3
        ):
            self.chamadas += 1
            if self.chamadas == 1:
                mensagem = ChatMessage(
                    role="assistant",
                    tool_calls=[ToolCall(id="c1", name="lenta", arguments={})],
                )
                fim = "tool_calls"
            else:
                mensagem = ChatMessage(role="assistant", content="nao devia chegar")
                fim = "stop"
            return LLMResponse(
                message=mensagem,
                usage=Usage(prompt_tokens=1, completion_tokens=1),
                provider="teste",
                model="teste",
                finish_reason=fim,
            )

    llm = LLMDuas()
    agente = ArisAgent(
        llm,
        PassthroughExecutor(registry),
        registry,
        FakeMemory(),
        FakeSkills(),
        AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data"),
    )

    resultado: list = []

    def rodar() -> None:
        resultado.append(agente.run("executa a lenta", "s1", AutoConfirm(True)))

    thread = threading.Thread(target=rodar)
    thread.start()
    assert iniciou.wait(timeout=10), "a ferramenta nunca comecou"
    agente.cancel("s1")  # outra thread pede cancelamento
    liberar.set()
    thread.join(timeout=30)
    assert not thread.is_alive(), "o laço travou"

    assert len(resultado) == 1
    res = resultado[0]
    assert res.ok is False and res.stopped_reason == "cancelled"
    assert llm.chamadas == 1  # não houve nova chamada ao LLM depois do cancel
