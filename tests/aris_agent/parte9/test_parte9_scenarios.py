"""Parte 9 — validação dos cenários de avaliação (sem executar o laço)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aris_agent.evals.scenarios import (
    CATEGORIAS_VALIDAS,
    SCENARIOS_DIR,
    ScenarioError,
    load_scenarios,
    parse_scenario,
)
from aris_agent.tools import discover
from aris_agent.tools.registry import ToolRegistry

MARCADORES_PERMITIDOS = {"{web}", "{workspace}"}


@pytest.fixture(scope="module")
def todos():
    return load_scenarios()


@pytest.fixture(scope="module")
def nomes_de_ferramenta() -> set[str]:
    registry = ToolRegistry()
    discover(registry)
    return {spec.name for spec in registry.specs()}


def test_tem_arquivos_de_cenario() -> None:
    arquivos = sorted(SCENARIOS_DIR.glob("*.jsonl"))
    assert len(arquivos) >= 10, "esperava um arquivo por categoria"


def test_quantidade_minima_por_categoria(todos) -> None:
    gerais = [c for c in todos if c.categoria != "seguranca"]
    adversariais = [c for c in todos if c.categoria == "seguranca"]
    assert len(todos) >= 90, f"só {len(todos)} cenários no total"
    assert len(gerais) >= 60, f"só {len(gerais)} cenários gerais"
    assert len(adversariais) >= 25, f"só {len(adversariais)} adversariais"


def test_ids_unicos_e_categorias_validas(todos) -> None:
    ids = [c.id for c in todos]
    assert len(ids) == len(set(ids))
    assert {c.categoria for c in todos} <= CATEGORIAS_VALIDAS


def test_toda_ferramenta_do_roteiro_existe(todos, nomes_de_ferramenta) -> None:
    desconhecidas: list[str] = []
    for cenario in todos:
        for item in cenario.roteiro:
            for chamada in item.ferramentas:
                if chamada["nome"] not in nomes_de_ferramenta:
                    desconhecidas.append(f"{cenario.id}: {chamada['nome']}")
    assert not desconhecidas, f"ferramentas inexistentes: {desconhecidas}"


def test_toda_ferramenta_esperada_existe(todos, nomes_de_ferramenta) -> None:
    desconhecidas: list[str] = []
    for cenario in todos:
        esp = cenario.esperado
        for nome in (
            esp.ferramentas_usadas
            + esp.ferramentas_proibidas
            + esp.ferramentas_ok
            + esp.ferramentas_negadas
        ):
            if nome not in nomes_de_ferramenta:
                desconhecidas.append(f"{cenario.id}: {nome}")
    assert not desconhecidas, f"ferramentas inexistentes: {desconhecidas}"


def test_marcadores_somente_os_permitidos(todos) -> None:
    import re

    padrao = re.compile(r"\{[a-z_]+\}")
    for cenario in todos:
        textos = [cenario.entrada] + [m.conteudo for m in cenario.roteiro]
        for item in cenario.roteiro:
            textos.extend(str(v) for v in item.ferramentas)
        for texto in textos:
            for marcador in padrao.findall(str(texto)):
                assert marcador in MARCADORES_PERMITIDOS, (
                    f"{cenario.id}: marcador desconhecido {marcador}"
                )


def test_cenario_malformado_levanta_erro() -> None:
    with pytest.raises(ScenarioError):
        parse_scenario({"categoria": "conversa", "entrada": "oi"}, source="x:1")
    with pytest.raises(ScenarioError):
        parse_scenario(
            {
                "id": "abc-001",
                "categoria": "inexistente",
                "entrada": "oi",
                "roteiro": [{"conteudo": "oi"}],
            },
            source="x:2",
        )


def test_arquivo_invalido_levanta_erro(tmp_path: Path) -> None:
    ruim = tmp_path / "ruim.jsonl"
    ruim.write_text("{isso nao e json}\n", encoding="utf-8")
    with pytest.raises(ScenarioError):
        load_scenarios(ruim)
