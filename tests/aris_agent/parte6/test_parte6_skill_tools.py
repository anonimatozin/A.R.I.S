"""Testes das ferramentas skill_load e skill_read_resource (Parte 6)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.protocols import SkillCatalog
from aris_agent.contract.types import Risk, ToolContext, ToolResult
from aris_agent.skills import SkillLibrary
from aris_agent.tools import ToolRegistry, discover, skill_tools
from aris_agent.tools.skill_tools import get_library, register, set_library

_PADRAO = "Descricao generica de teste, valida o bastante para o catalogo."


def _skill(raiz: Path, nome: str, descricao: str = _PADRAO) -> Path:
    pasta = raiz / nome
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "SKILL.md").write_text(
        f"---\nname: {nome}\ndescription: {descricao}\n---\n\n## Objetivo\n\nfaz a coisa.\n",
        encoding="utf-8",
    )
    (pasta / "references").mkdir()
    (pasta / "references" / "guia.md").write_text("# Guia\nleia isto\n", encoding="utf-8")
    return pasta


@pytest.fixture()
def ctx(tmp_path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(
        session_id="sessao-teste",
        workdir=tmp_path,
        config=cfg,
        cancel=threading.Event(),
    )


@pytest.fixture()
def lib(tmp_path) -> SkillLibrary:
    _skill(tmp_path, "minha-skill")
    return SkillLibrary([tmp_path])


@pytest.fixture(autouse=True)
def _biblioteca_zerada():
    """Garante que a injeção global comece e termine nula em cada teste."""
    set_library(None)
    yield
    set_library(None)


def _ferramenta(nome: str):
    registry = ToolRegistry()
    register(registry)
    return registry.get(nome)


def test_set_e_get_library(lib: SkillLibrary) -> None:
    assert get_library() is None
    set_library(lib)
    assert get_library() is lib


def test_sem_biblioteca_responde_ok_false(ctx: ToolContext) -> None:
    for nome, args in (
        ("skill_load", {"name": "x"}),
        ("skill_read_resource", {"name": "x", "relative_path": "a.md"}),
    ):
        tool = _ferramenta(nome)
        resultado = tool.run(args, ctx)
        assert isinstance(resultado, ToolResult)
        assert resultado.ok is False
        assert "set_library" in resultado.error
        assert resultado.content == ""


def test_skill_load_devolve_conteudo(lib: SkillLibrary, ctx: ToolContext) -> None:
    set_library(lib)
    resultado = _ferramenta("skill_load").run({"name": "minha-skill"}, ctx)
    assert resultado.ok, resultado.error
    assert "# Skill: minha-skill" in resultado.content
    assert "faz a coisa." in resultado.content
    assert resultado.data == {"name": "minha-skill", "resources": ["references/guia.md"]}


def test_skill_load_nome_desconhecido(lib: SkillLibrary, ctx: ToolContext) -> None:
    set_library(lib)
    resultado = _ferramenta("skill_load").run({"name": "nao-existe"}, ctx)
    assert resultado.ok is False
    assert "skill desconhecida" in resultado.error
    assert "minha-skill" in resultado.error


@pytest.mark.parametrize("args", [{"name": ""}, {"name": "   "}, {}, {"name": 42}])
def test_skill_load_nome_invalido(lib: SkillLibrary, ctx: ToolContext, args: dict) -> None:
    set_library(lib)
    resultado = _ferramenta("skill_load").run(args, ctx)
    assert resultado.ok is False
    assert "name" in resultado.error


def test_skill_load_trunca_conteudo(lib: SkillLibrary, ctx: ToolContext) -> None:
    ctx.config.max_tool_chars = 60
    set_library(lib)
    resultado = _ferramenta("skill_load").run({"name": "minha-skill"}, ctx)
    assert resultado.ok
    assert len(resultado.content) <= 60
    assert "omitidos" in resultado.content


def test_skill_read_resource_ok(lib: SkillLibrary, ctx: ToolContext) -> None:
    set_library(lib)
    resultado = _ferramenta("skill_read_resource").run(
        {"name": "minha-skill", "relative_path": "references/guia.md"}, ctx
    )
    assert resultado.ok, resultado.error
    assert "leia isto" in resultado.content
    assert resultado.data["relative_path"] == "references/guia.md"


def test_skill_read_resource_traversal_bloqueado(lib: SkillLibrary, ctx: ToolContext) -> None:
    set_library(lib)
    resultado = _ferramenta("skill_read_resource").run(
        {"name": "minha-skill", "relative_path": "../../etc/passwd"}, ctx
    )
    assert resultado.ok is False
    assert ".." in resultado.error


def test_skill_read_resource_sem_caminho(lib: SkillLibrary, ctx: ToolContext) -> None:
    set_library(lib)
    resultado = _ferramenta("skill_read_resource").run({"name": "minha-skill"}, ctx)
    assert resultado.ok is False
    assert "relative_path" in resultado.error


def test_specs_das_ferramentas() -> None:
    registry = ToolRegistry()
    register(registry)
    nomes = {spec.name for spec in registry.specs()}
    assert {"skill_load", "skill_read_resource"} <= nomes
    for spec in registry.specs():
        assert spec.risk == Risk.READ
        assert spec.tags == ("skills",)
    assert registry.get("skill_read_resource").spec.path_args == ("relative_path",)


def test_register_e_idempotente() -> None:
    registry = ToolRegistry()
    register(registry)
    registro = len(registry)
    register(registry)
    assert len(registry) == registro


def test_biblioteca_e_skill_catalog(lib: SkillLibrary) -> None:
    set_library(lib)
    assert isinstance(get_library(), SkillCatalog)


def test_descoberta_no_pacote_real_registra_ferramentas() -> None:
    registry = ToolRegistry()
    processados = discover(registry)
    assert "skill_tools" in processados
    assert "skill_load" in registry and "skill_read_resource" in registry


def test_modulo_expoe_ponto_de_injecao() -> None:
    assert callable(skill_tools.set_library)
    assert callable(skill_tools.get_library)
    assert callable(skill_tools.register)
