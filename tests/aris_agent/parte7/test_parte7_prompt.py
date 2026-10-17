"""Testes do PromptBuilder e das heurísticas do agente (Parte 7)."""

from __future__ import annotations

from datetime import datetime

from aris_agent.config import AgentConfig
from aris_agent.contract import Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.contract.types import ChatMessage
from aris_agent.core import ArisAgent, PromptBuilder
from aris_agent.core.heuristics import (
    asks_to_verify,
    choose_difficulty,
    looks_like_correction,
    looks_trivial,
)
from aris_agent.fakes import AutoConfirm, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from aris_agent.tools import ToolRegistry, function_tool


def cfg(tmp_path) -> AgentConfig:
    return AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")


def montar(tmp_path, script, ferramentas=(), memoria=None, skills=None):
    registry = ToolRegistry()
    for tool in ferramentas:
        registry.register(tool)
    llm = FakeLLM(script)
    memoria = memoria or FakeMemory()
    agente = ArisAgent(
        llm,
        PassthroughExecutor(registry),
        registry,
        memoria,
        skills or FakeSkills(),
        cfg(tmp_path),
    )
    return agente, llm


def chamada(nome: str, args: dict, id_: str = "c1") -> ChatMessage:
    return ChatMessage(role="assistant", tool_calls=[ToolCall(id=id_, name=nome, arguments=args)])


def ferramenta_gravando(nome: str, captura: list, params=None):
    spec = ToolSpec(
        name=nome,
        description=f"ferramenta {nome}",
        parameters=params or {"type": "object", "properties": {}},
        risk=Risk.READ,
        tags=("memoria",),
    )

    @function_tool(spec)
    def _f(args: dict, ctx: ToolContext) -> ToolResult:
        captura.append(dict(args))
        return ToolResult(ok=True, content="gravado")

    return _f


def prompt_de(llm) -> str:
    return llm.calls[0]["messages"][0].content


# ------------------------------------------------------------ PromptBuilder


def test_prompt_identidade_e_regras() -> None:
    texto = PromptBuilder().build("oi", workspace="C:/ARIS_workspace")
    assert "A.R.I.S." in texto
    assert "Vinicius" in texto and "chefe" in texto
    assert "Data e hora atuais" in texto
    assert "Regras de ouro" in texto
    assert "resultado ok de ferramenta" in texto
    assert "unica chamada" in texto
    assert "C:/ARIS_workspace" in texto
    assert "plan_update" in texto  # instrução de plano mesmo sem plano


def test_prompt_data_hora_com_dia_da_semana() -> None:
    texto = PromptBuilder().build("oi", now=datetime(2026, 10, 4, 15, 30))
    assert "domingo, 04/10/2026 as 15:30" in texto


def test_prompt_com_skills_e_memorias(tmp_path) -> None:
    skills = FakeSkills({"relatorio": ("gera um relatorio curto", "corpo da skill")})
    memoria = FakeMemory()
    memoria.remember("o Vinicius toma cafe todo dia", kind="fact")
    agente, llm = montar(
        tmp_path,
        [ChatMessage(role="assistant", content="ok, chefe")],
        skills=skills,
        memoria=memoria,
    )
    agente.run("qual era o cafe que eu gosto?", "s1", AutoConfirm(True))
    prompt = prompt_de(llm)

    assert "relatorio: gera um relatorio curto" in prompt
    assert "skill_load" in prompt
    assert "Informacoes lembradas" in prompt
    assert "podem estar desatualizadas" in prompt
    assert "toma cafe todo dia" in prompt


def test_prompt_sem_memorias_nem_skills(tmp_path) -> None:
    agente, llm = montar(tmp_path, [ChatMessage(role="assistant", content="ok")])
    agente.run("bom dia", "s1", AutoConfirm(True))
    prompt = prompt_de(llm)
    assert "Informacoes lembradas" not in prompt
    assert "Skills disponiveis" not in prompt


def test_prompt_reforca_correcao_com_lesson(tmp_path) -> None:
    captura: list = []
    params = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "kind": {"type": "string"}},
        "required": ["text", "kind"],
    }
    agente, llm = montar(
        tmp_path,
        [
            chamada("memory_remember", {"text": "o certo e usar pytest", "kind": "lesson"}, "c1"),
            ChatMessage(role="assistant", content="anotado, chefe!"),
        ],
        ferramentas=[ferramenta_gravando("memory_remember", captura, params=params)],
    )
    res = agente.run("nao, o certo e usar pytest", "s1", AutoConfirm(True))

    prompt = prompt_de(llm)
    assert "memory_remember" in prompt and 'kind="lesson"' in prompt
    assert "corrigindo" in prompt
    assert captura and captura[0]["kind"] == "lesson"
    assert res.ok


# ------------------------------------------------------------- heurísticas


def test_looks_trivial() -> None:
    assert looks_trivial("oi")
    assert looks_trivial("bom dia, chefe")
    assert looks_trivial("obrigado!")
    assert looks_trivial("tudo bem por aqui")
    assert not looks_trivial("pesquisa no site sobre precos")
    assert not looks_trivial("cria um arquivo novo na pasta")
    assert not looks_trivial("abre o programa de edicao")


def test_looks_like_correction() -> None:
    assert looks_like_correction("nao, o certo e usar pytest")
    assert looks_like_correction("errado, e com a virgula")
    assert looks_like_correction("voce errou o caminho")
    assert looks_like_correction("está errado isso")
    assert not looks_like_correction("bom dia, chefe")
    assert not looks_like_correction("pesquisa precos de carros")
    assert not looks_like_correction("")


def test_asks_to_verify() -> None:
    assert asks_to_verify("confira se o resultado esta certo")
    assert asks_to_verify("verifique de novo, por favor")
    assert asks_to_verify("tem certeza disso?")
    assert not asks_to_verify("cria um arquivo novo")
    assert not asks_to_verify("bom dia")


def test_choose_difficulty() -> None:
    casos = [
        ("bom dia", True, 0, 0, 0, "easy"),
        ("pesquisa precos", True, 0, 0, 0, "normal"),
        ("pesquisa precos", True, 3, 0, 0, "hard"),
        ("bom dia", True, 0, 4, 0, "hard"),
        ("bom dia", True, 0, 0, 1, "hard"),
        ("oi", False, 0, 0, 0, "normal"),
    ]
    for texto, first, plano, chamadas, correcoes, esperado in casos:
        obtido = choose_difficulty(
            texto,
            first=first,
            plan_size=plano,
            tool_calls_done=chamadas,
            corrections=correcoes,
        )
        assert obtido == esperado, f"{texto!r}: {obtido} != {esperado}"


def test_memoria_items_no_prompt(tmp_path) -> None:
    memoria = FakeMemory()
    memoria.remember("preferencia: respostas curtas", kind="preference")
    agente, llm = montar(
        tmp_path,
        [ChatMessage(role="assistant", content="ok")],
        memoria=memoria,
    )
    agente.run("qual a preferencia mesmo", "s1", AutoConfirm(True))
    prompt = prompt_de(llm)
    assert "Informacoes lembradas" in prompt
    assert "(preference) preferencia: respostas curtas" in prompt
