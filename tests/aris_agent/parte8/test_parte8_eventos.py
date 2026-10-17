"""Parte 8 — eventos do agente → falas curtas (sem repetir em sequência)."""

from __future__ import annotations

from aris_agent.bridge.eventos import FaladorDeEventos
from aris_agent.contract.types import AgentEvent


def _tool_call(nome: str) -> AgentEvent:
    return AgentEvent(type="tool_call", data={"name": nome, "args": {}})


def test_fala_ferramenta_conhecida() -> None:
    falado: list[str] = []
    falador = FaladorDeEventos(falado.append)
    falador(_tool_call("web_search"))
    assert falado == ["pesquisando na web..."]
    assert falador.total_falado == 1


def test_nao_repete_frase_seguida() -> None:
    falado: list[str] = []
    falador = FaladorDeEventos(falado.append)
    falador(_tool_call("web_search"))
    falador(_tool_call("web_search"))  # mesma em sequência: silêncio
    falador(_tool_call("web_search"))
    assert falado == ["pesquisando na web..."]


def test_reset_libera_repeticao_e_ferramenta_diferente_fala() -> None:
    falado: list[str] = []
    falador = FaladorDeEventos(falado.append)
    falador(_tool_call("web_search"))
    falador(_tool_call("pc_read_file"))
    falador.reset()
    falador(_tool_call("pc_read_file"))
    assert len(falado) == 3
    assert falado[1] == "lendo o arquivo..."
    assert falado[2] == "lendo o arquivo..."


def test_ferramenta_desconhecida_e_outros_eventos_silenciosos() -> None:
    falado: list[str] = []
    falador = FaladorDeEventos(falado.append)
    falador(_tool_call("ferramenta_misteriosa"))
    falador(AgentEvent(type="plan", data={"steps": 2}))
    falador(AgentEvent(type="tool_result", data={"name": "web_search"}))
    falador(AgentEvent(type="final", data={"text": "pronto"}))
    assert falado == []


def test_falar_que_quebra_nao_derruba_o_evento() -> None:
    def falar(_texto: str) -> None:
        raise RuntimeError("voz morreu")

    falador = FaladorDeEventos(falar)
    falador(_tool_call("memory_remember"))  # não pode lançar
    # voz falhou: nada foi de fato falado, mas o evento não derrubou o laço
    assert falador.total_falado == 0
    falador(_tool_call("web_search"))  # próximo evento segue processando
    assert falador.total_falado == 0
