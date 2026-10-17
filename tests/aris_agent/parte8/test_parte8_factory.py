"""Parte 8 — fábrica: perfis desktop/edge e falhas que desligam com aviso."""

from __future__ import annotations

import pytest

from aris_agent.bridge.factory import build_agent
from aris_agent.config import AgentConfig
from aris_agent.fakes import FakeLLM


@pytest.fixture
def cfg(tmp_path) -> AgentConfig:
    return AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        agent_enabled=True,
        max_steps=6,
        sections={},
    )


def _nomes(pacote) -> set[str]:
    return {spec.name for spec in pacote.registry.specs()}


def test_perfil_desconhecido_devolve_none(cfg) -> None:
    assert build_agent(cfg, perfil="celular", llm=FakeLLM()) is None


def test_perfil_desktop_registra_todos_os_grupos(cfg) -> None:
    pacote = build_agent(cfg, perfil="desktop", llm=FakeLLM())
    assert pacote is not None
    nomes = _nomes(pacote)
    assert {"pc_delete_file", "web_search", "memory_remember"} <= nomes
    assert pacote.perfil == "desktop"
    assert pacote.kill_switch is pacote.executor.kill_switch


def test_perfil_edge_so_web_e_memoria(cfg) -> None:
    pacote = build_agent(cfg, perfil="edge", llm=FakeLLM())
    assert pacote is not None
    nomes = _nomes(pacote)
    assert {"web_search", "memory_remember"} <= nomes
    assert not any(n.startswith("pc_") for n in nomes), f"ferramenta de PC no edge: {nomes}"
    assert not any(n.startswith("browser_") for n in nomes)
    assert not any(n.startswith("skill_") for n in nomes)
    # só o que sobra é a ferramenta interna do agente (plan_update)
    sobra = nomes - {n for n in nomes if n.startswith(("web_", "memory_"))}
    assert sobra <= {"plan_update"}, f"sobra inesperada no edge: {sobra}"


def test_sem_provedores_llm_devolve_none(cfg) -> None:
    # llm=None exige a seção "llm" do aris_agent.json; sem ela, nada de rede
    assert build_agent(cfg, llm=None) is None


def test_llm_injetado_nao_toca_na_configuracao(cfg) -> None:
    # testes injetam FakeLLM: nenhuma dependência de arquivos/chaves
    pacote = build_agent(cfg, perfil="desktop", llm=FakeLLM())
    assert pacote is not None
    assert pacote.agente is not None
