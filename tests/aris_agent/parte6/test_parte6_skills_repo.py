"""Valida todas as skills iniciais do repositório (Parte 6).

Roda contra `aris_skills/` de verdade: formato, nome igual à pasta,
descrição presente e corpo com menos de ~150 linhas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aris_agent.skills import (
    SkillLibrary,
    parse_frontmatter,
    project_skills_dir,
    validar_campos,
)

RAIZ = project_skills_dir()
ESPERADAS = {
    "controle-do-windows",
    "criar-skill",
    "depuracao-de-codigo",
    "organizar-arquivos",
    "pesquisa-web",
    "relatorio-comparativo",
}
_MAX_LINHAS = 150


def _pastas() -> list[Path]:
    if not RAIZ.is_dir():
        return []
    return sorted((p for p in RAIZ.iterdir() if p.is_dir()), key=lambda p: p.name)


PASTAS = _pastas()
NOMES = [p.name for p in PASTAS]


def test_pasta_do_repositorio_existe() -> None:
    assert RAIZ.is_dir(), f"pasta de skills do projeto não encontrada: {RAIZ}"


def test_as_seis_iniciais_estao_presentes() -> None:
    assert ESPERADAS <= set(NOMES), f"faltando: {ESPERADAS - set(NOMES)}"


@pytest.mark.parametrize("nome", NOMES, ids=NOMES)
def test_skill_do_repositorio_valida(nome: str) -> None:
    pasta = RAIZ / nome
    md = pasta / "SKILL.md"
    assert md.is_file(), f"{pasta.name}: falta o SKILL.md"
    texto = md.read_text(encoding="utf-8")
    linhas = texto.splitlines()

    campos, corpo = parse_frontmatter(texto)
    nome_fm, descricao = validar_campos(campos)
    assert nome_fm == pasta.name, "name do frontmatter difere da pasta"
    assert len(descricao) <= 1024
    assert len(descricao) >= 40, "descrição curta demais para dizer quando usar"
    assert len(linhas) <= _MAX_LINHAS, f"{nome}: {len(linhas)} linhas (máx. {_MAX_LINHAS})"
    assert corpo.strip(), "corpo do SKILL.md vazio"
    assert "\n## " in "\n" + corpo, "corpo sem seção '## ...'"


@pytest.mark.parametrize("nome", sorted(ESPERADAS), ids=sorted(ESPERADAS))
def test_descricao_diz_quando_usar(nome: str) -> None:
    campos, _ = parse_frontmatter((RAIZ / nome / "SKILL.md").read_text(encoding="utf-8"))
    descricao = str(campos["description"])
    assert "quando" in descricao.lower(), "descrição deve dizer quando usar a skill"


def test_todas_carregam_na_biblioteca() -> None:
    lib = SkillLibrary([RAIZ])
    assert set(lib.names()) == set(NOMES)
    for nome in NOMES:
        texto = lib.load(nome)
        assert texto.startswith(f"# Skill: {nome}")
        assert "Descrição: " in texto


def test_catalog_prompt_uma_linha_por_skill() -> None:
    lib = SkillLibrary([RAIZ])
    linhas = lib.catalog_prompt().splitlines()
    assert len(linhas) == len(NOMES)
    assert all(linha.startswith("- ") for linha in linhas)
    for nome in NOMES:
        assert any(linha.startswith(f"- {nome}: ") for linha in linhas)


def test_recursos_do_repositorio_estao_listados() -> None:
    lib = SkillLibrary([RAIZ])
    assert "references/como-citar.md" in lib.resources("pesquisa-web")
    assert "references/modelo-skill.md" in lib.resources("criar-skill")
    assert "scripts/inventariar.py" in lib.resources("organizar-arquivos")
    # leitura real de um recurso do repositório
    guia = lib.read_resource("pesquisa-web", "references/como-citar.md")
    assert "AAAA-MM-DD" in guia


def test_nenhum_segredo_obvio_nas_skills() -> None:
    proibidos = ("gsk_", "sk-ant-", "api_key=", "password=", "AKIA")
    for pasta in PASTAS:
        texto = (pasta / "SKILL.md").read_text(encoding="utf-8")
        for marca in proibidos:
            assert marca not in texto, f"{pasta.name}: contém {marca!r}"
