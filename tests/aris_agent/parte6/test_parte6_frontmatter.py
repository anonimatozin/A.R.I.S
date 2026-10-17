"""Testes do parser de frontmatter do SKILL.md (Parte 6)."""

from __future__ import annotations

import pytest

from aris_agent.skills.frontmatter import (
    FrontmatterError,
    parse_frontmatter,
    validar_campos,
    validar_descricao,
    validar_nome,
)

VALIDO = """---
name: minha-skill
description: Faz a coisa certa quando o usuario pedir. Use quando precisar disso.
---

## Objetivo

faz a coisa
"""


def test_parse_valido_sem_aspas() -> None:
    campos, corpo = parse_frontmatter(VALIDO)
    assert campos["name"] == "minha-skill"
    assert campos["description"].startswith("Faz a coisa")
    assert corpo.startswith("## Objetivo")
    assert "faz a coisa" in corpo


def test_parse_remove_aspas_duplas_e_simples() -> None:
    campos, _ = parse_frontmatter(
        '---\nname: "minha-skill"\ndescription: \'descricao com aspas\'\n---\n'
    )
    assert campos["name"] == "minha-skill"
    assert campos["description"] == "descricao com aspas"


def test_parse_ignora_comentario_de_linha_e_inline() -> None:
    campos, _ = parse_frontmatter(
        "---\n"
        "# comentario de linha inteira\n"
        "name: minha-skill\n"
        "description: serve para testar # comentario inline\n"
        "license: MIT   # licenca qualquer\n"
        "---\n"
    )
    assert campos["description"] == "serve para testar"
    assert campos["license"] == "MIT"
    assert "comentario de linha" not in campos


def test_parse_preserva_campos_extras_e_aninhados() -> None:
    campos, _ = parse_frontmatter(
        "---\n"
        "name: minha-skill\n"
        "description: descricao curta e valida o bastante.\n"
        "allowed-tools: skill_load\n"
        "metadata:\n"
        "  autor: aris\n"
        "  version: 1\n"
        "---\n"
    )
    assert campos["allowed-tools"] == "skill_load"
    assert campos["metadata"] == {"autor": "aris", "version": "1"}
    assert set(campos) >= {"name", "description", "allowed-tools", "metadata"}


def test_parse_sem_frontmatter_levanta() -> None:
    with pytest.raises(FrontmatterError, match="começar com"):
        parse_frontmatter("# so markdown\n\nconteudo\n")


def test_parse_frontmatter_nao_terminado_levanta() -> None:
    with pytest.raises(FrontmatterError, match="não terminado"):
        parse_frontmatter("---\nname: minha-skill\n\ndescription: caiu fora\n")


def test_parse_linha_invalida_levanta() -> None:
    with pytest.raises(FrontmatterError, match="linha 2 inválida"):
        parse_frontmatter("---\nisso nao eh par\n---\n")


def test_parse_valor_vazio_vira_bloco_aninhado() -> None:
    campos, _ = parse_frontmatter("---\nname: minha-skill\nmetadata:\n---\n")
    assert campos["metadata"] == {}


def test_parse_aceita_bom_e_crlf() -> None:
    texto = "\ufeff---\r\nname: minha-skill\r\ndescription: valido com crlf\r\n---\r\n\r\ncorpo\r\n"
    campos, corpo = parse_frontmatter(texto)
    assert campos["name"] == "minha-skill"
    assert "corpo" in corpo


def test_parse_corpo_pode_ser_vazio() -> None:
    campos, corpo = parse_frontmatter("---\nname: x\ndescription: y\n---\n")
    assert corpo == ""
    assert campos["name"] == "x"


@pytest.mark.parametrize(
    "nome",
    ["MINHA", "Minha-skill", "-comeca", "termina-", "dois--hifen", "tem espaço", "", "a" * 65],
)
def test_validar_nome_rejeita(nome: str) -> None:
    with pytest.raises(FrontmatterError):
        validar_nome(nome)


@pytest.mark.parametrize("nome", ["a", "minha-skill", "skill2", "a1-b2-c3", "x" * 64])
def test_validar_nome_aceita(nome: str) -> None:
    assert validar_nome(nome) == nome


def test_validar_nome_rejeita_nao_texto() -> None:
    with pytest.raises(FrontmatterError, match="name"):
        validar_nome(None)


def test_validar_descricao_limites() -> None:
    with pytest.raises(FrontmatterError, match="description"):
        validar_descricao("   ")
    with pytest.raises(FrontmatterError, match="1024"):
        validar_descricao("x" * 1025)
    assert validar_descricao("x" * 1024) == "x" * 1024


def test_validar_campos_devolve_tupla() -> None:
    campos, _ = parse_frontmatter(VALIDO)
    nome, descricao = validar_campos(campos)
    assert nome == "minha-skill"
    assert "Use quando" in descricao


def test_validar_campos_com_metadata_nao_quebra() -> None:
    campos, _ = parse_frontmatter(
        "---\nname: minha-skill\ndescription: descricao valida o bastante sim.\n"
        "metadata:\n  autor: eu\n---\n"
    )
    assert validar_campos(campos)[0] == "minha-skill"
