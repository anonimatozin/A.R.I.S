"""Testes do ToolSelector e da aceitação de ferramentas fora do envio (Parte 7)."""

from __future__ import annotations

from aris_agent.config import AgentConfig
from aris_agent.contract import Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import MAX_TOOLS, ArisAgent, ToolSelector
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool


def ferramenta(nome: str, descricao: str | None = None, tags: tuple = ("teste",)):
    spec = ToolSpec(
        name=nome,
        description=descricao or f"ferramenta {nome} de teste",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=tags,
    )

    @function_tool(spec)
    def _f(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content="ok")

    return _f


def nomes(select: list) -> list[str]:
    return [spec.name for spec in select]


def test_nucleo_sempre_enviado() -> None:
    registry = ToolRegistry(
        [
            ferramenta("calc"),
            ferramenta("skill_load"),
            ferramenta("memory_recall"),
            ferramenta("outra", descricao="qualquer coisa"),
        ]
    )
    selecionadas = ToolSelector(registry).select("bom dia, chefe")
    assert sorted(nomes(selecionadas)) == ["calc", "memory_recall", "skill_load"]


def test_grupo_web_ativado_por_palavra() -> None:
    registry = ToolRegistry(
        [
            ferramenta("busca_web", tags=("web",)),
            ferramenta("futebol", descricao="placar de futebol", tags=("esporte",)),
        ]
    )
    texto = "pesquisa na web sobre clima"
    selecionadas = nomes(ToolSelector(registry).select(texto))
    assert "busca_web" in selecionadas
    assert "futebol" not in selecionadas


def test_grupo_arquivos_ativado_por_palavra() -> None:
    registry = ToolRegistry(
        [
            ferramenta("le_arquivo", tags=("files",)),
            ferramenta("jogo", descricao="abre um jogo", tags=("lazer",)),
        ]
    )
    selecionadas = nomes(ToolSelector(registry).select("le o arquivo de texto"))
    assert "le_arquivo" in selecionadas
    assert "jogo" not in selecionadas


def test_ferramenta_ja_usada_sempre_volta() -> None:
    registry = ToolRegistry([ferramenta("ferramenta_rara", descricao="nada a ver com nada")])
    selecionadas = ToolSelector(registry).select("bom dia", used=["ferramenta_rara"])
    assert "ferramenta_rara" in nomes(selecionadas)


def test_limite_de_ferramentas_enviadas() -> None:
    registry = ToolRegistry(
        [
            ferramenta(f"banco_{i}", descricao=f"ferramenta {i} para teste de banco de dados")
            for i in range(15)
        ]
    )
    selecionadas = ToolSelector(registry).select("teste banco de dados")
    assert 0 < len(selecionadas) <= MAX_TOOLS


def test_selecao_por_nome_e_descricao() -> None:
    registry = ToolRegistry(
        [
            ferramenta("clima_tempo", descricao="previsao do tempo"),
            ferramenta("agenda", descricao="compromissos do calendario"),
        ]
    )
    selecionadas = nomes(ToolSelector(registry).select("previsao do tempo de hoje"))
    assert "clima_tempo" in selecionadas
    assert "agenda" not in selecionadas


def test_registry_vazio_nao_quebra() -> None:
    assert ToolSelector(ToolRegistry()).select("qualquer coisa") == []


def test_ferramenta_fora_do_envio_e_aceita_e_entra_depois(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ferramenta("rara_x", descricao="disponivel sob pedido"))
    llm = FakeLLM(
        [
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(id="c1", name="rara_x", arguments={})],
            ),
            ChatMessage(role="assistant", content="feito, chefe."),
        ]
    )
    executor = PassthroughExecutor(registry)
    agente = ArisAgent(
        llm,
        executor,
        registry,
        FakeMemory(),
        FakeSkills(),
        AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data"),
    )
    res = agente.run("faz a coisa agora mesmo", "s1", AutoConfirm(True))

    assert res.ok and res.tool_calls == 1
    assert executor.calls[0].name == "rara_x"  # aceita mesmo fora do envio
    assert "rara_x" not in nomes(llm.calls[0]["tools"])
    assert "rara_x" in nomes(llm.calls[1]["tools"])  # e passa a ser enviada
