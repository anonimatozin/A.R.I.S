"""Testes da memória no laço (Parte 7): turnos, redação e lições de correção."""

from __future__ import annotations

from aris_agent.config import AgentConfig
from aris_agent.contract import Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import ArisAgent
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool


def cfg(tmp_path) -> AgentConfig:
    return AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")


def chamada(nome: str, args: dict, id_: str = "c1") -> ChatMessage:
    return ChatMessage(role="assistant", tool_calls=[ToolCall(id=id_, name=nome, arguments=args)])


def fim(texto: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=texto)


def ferramenta_gravando(nome: str, captura: list, params=None, tags=("memoria",)):
    spec = ToolSpec(
        name=nome,
        description=f"ferramenta {nome}",
        parameters=params or {"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=tags,
    )

    @function_tool(spec)
    def _f(args: dict, ctx: ToolContext) -> ToolResult:
        captura.append(dict(args))
        return ToolResult(ok=True, content="gravado")

    return _f


def montar(tmp_path, script, ferramentas=(), memoria=None):
    registry = ToolRegistry()
    for tool in ferramentas:
        registry.register(tool)
    llm = FakeLLM(script)
    memoria = memoria or FakeMemory()
    agente = ArisAgent(
        llm, PassthroughExecutor(registry), registry, memoria, FakeSkills(), cfg(tmp_path)
    )
    return agente, llm, memoria


def test_turnos_gravados_com_redacao(tmp_path) -> None:
    agente, _, memoria = montar(tmp_path, [fim("anotado, chefe")])
    texto_user = "minha senha=hsegredo123 para o servidor"
    res = agente.run(texto_user, "s1", AutoConfirm(True))

    turnos = memoria.recent_turns("s1", 10)
    assert [t.role for t in turnos] == ["user", "assistant"]
    assert "hsegredo123" not in turnos[0].content
    assert "[REDACTED]" in turnos[0].content
    assert turnos[1].content == res.text == "anotado, chefe"


def test_turnos_anteriores_entram_no_proximo_turno(tmp_path) -> None:
    memoria = FakeMemory()
    agente1, _, _ = montar(tmp_path, [fim("primeira resposta")], memoria=memoria)
    agente1.run("primeiro pedido", "s1", AutoConfirm(True))

    agente2, llm2, _ = montar(tmp_path, [fim("segunda resposta")], memoria=memoria)
    agente2.run("segundo pedido", "s1", AutoConfirm(True))

    mensagens = llm2.calls[0]["messages"]
    papeis = [m.role for m in mensagens]
    assert papeis[:4] == ["system", "user", "assistant", "user"]
    assert mensagens[1].content == "primeiro pedido"
    assert mensagens[2].content == "primeira resposta"
    assert mensagens[3].content == "segundo pedido"


def test_correcao_gera_lesson(tmp_path) -> None:
    captura: list = []
    params = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "kind": {"type": "string"}},
        "required": ["text", "kind"],
    }
    agente, llm, _ = montar(
        tmp_path,
        [
            chamada("memory_remember", {"text": "o certo e usar pytest", "kind": "lesson"}, "c1"),
            fim("anotado, chefe!"),
        ],
        ferramentas=[ferramenta_gravando("memory_remember", captura, params=params)],
    )
    res = agente.run("nao, o certo e usar pytest", "s1", AutoConfirm(True))

    assert res.ok
    assert captura == [{"text": "o certo e usar pytest", "kind": "lesson"}]
    # a instrução de correção veio no prompt da primeira chamada
    prompt = llm.calls[0]["messages"][0].content
    assert 'kind="lesson"' in prompt


def test_memoria_de_recall_no_prompt(tmp_path) -> None:
    memoria = FakeMemory()
    memoria.remember("senha do wifi e na etiqueta do roteador", kind="fact")
    agente, llm, _ = montar(tmp_path, [fim("etiqueta do roteador, chefe")], memoria=memoria)
    agente.run("onde fica a senha do wifi", "s1", AutoConfirm(True))

    prompt = llm.calls[0]["messages"][0].content
    assert "Informacoes lembradas" in prompt
    assert "senha do wifi e na etiqueta do roteador" in prompt


def test_add_turn_nao_derruba_com_memoria_ruim(tmp_path) -> None:
    class MemoriaQuebrada(FakeMemory):
        def add_turn(self, session_id, role, content) -> None:
            raise RuntimeError("banco fora do ar")

    agente, _, _ = montar(tmp_path, [fim("seguimos")], memoria=MemoriaQuebrada())
    res = agente.run("oi chefe", "s1", AutoConfirm(True))
    assert res.ok and res.text == "seguimos"


def test_recall_quebrado_nao_derruba(tmp_path) -> None:
    class MemoriaQuebrada(FakeMemory):
        def recall(self, query, k=5, kinds=None):
            raise RuntimeError("indice corrompido")

    agente, llm, _ = montar(tmp_path, [fim("ok")], memoria=MemoriaQuebrada())
    res = agente.run("onde esta o arquivo", "s1", AutoConfirm(True))
    assert res.ok
    assert "Informacoes lembradas" not in llm.calls[0]["messages"][0].content
