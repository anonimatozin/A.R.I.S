"""Testes das ferramentas de memória: registro, injeção e caminhos de erro (Parte 4)."""

from __future__ import annotations

import threading
import uuid

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.types import Risk, ToolContext
from aris_agent.memory import SqliteMemory
from aris_agent.tools import ToolRegistry, discover
from aris_agent.tools.memory_tools import get_memory, register, set_memory

NOMES = ("memory_remember", "memory_recall", "memory_forget")


@pytest.fixture(autouse=True)
def sem_memoria():
    set_memory(None)
    yield
    set_memory(None)


@pytest.fixture
def memoria(tmp_path) -> SqliteMemory:
    instance = SqliteMemory(tmp_path / "memory.sqlite3")
    yield instance
    instance.close()


def make_ctx(tmp_path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(
        session_id="s1", workdir=tmp_path, config=cfg, cancel=threading.Event()
    )


def run(nome: str, args: dict, ctx: ToolContext):
    registry = ToolRegistry()
    register(registry)
    tool = registry.get(nome)
    return tool.run(args, ctx)  # type: ignore[attr-defined]


def test_registra_as_tres_ferramentas() -> None:
    registry = ToolRegistry()
    register(registry)
    assert {spec.name for spec in registry.specs()} == set(NOMES)


def test_register_e_idempotente() -> None:
    registry = ToolRegistry()
    register(registry)
    register(registry)  # segunda chamada não pode levantar ToolError
    assert len(registry) == 3


def test_specs_risco_e_flags() -> None:
    registry = ToolRegistry()
    register(registry)
    specs = {spec.name: spec for spec in registry.specs()}
    assert specs["memory_remember"].risk == Risk.WRITE
    assert specs["memory_recall"].risk == Risk.READ
    assert specs["memory_forget"].risk == Risk.WRITE
    assert specs["memory_forget"].untrusted_output is False
    assert specs["memory_recall"].untrusted_output is True
    for spec in specs.values():
        assert spec.tags == ("memory",)
        assert spec.parameters["type"] == "object"


def test_descricao_ensina_a_guardar_lessons() -> None:
    registry = ToolRegistry()
    register(registry)
    spec = next(s for s in registry.specs() if s.name == "memory_remember")
    assert "lesson" in spec.description
    assert "corrig" in spec.description  # "quando o usuário te corrigir..."
    assert spec.parameters["properties"]["kind"]["enum"] == [
        "fact",
        "preference",
        "lesson",
        "episode",
    ]


def test_descoberta_automatica() -> None:
    registry = ToolRegistry()
    processados = discover(registry)
    assert "memory_tools" in processados
    assert {spec.name for spec in registry.specs()} >= set(NOMES)


def test_sem_memoria_responde_ok_false(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    for nome in NOMES:
        args = {"text": "x", "query": "x", "id": "x"}
        result = run(nome, args, ctx)
        assert result.ok is False, nome
        assert result.content == ""
        assert "set_memory" in (result.error or ""), nome


def test_com_memoria_fluxo_completo(tmp_path, memoria) -> None:
    set_memory(memoria)
    ctx = make_ctx(tmp_path)

    guardado = run(
        "memory_remember",
        {"text": "Vinicius prefere café sem açúcar", "kind": "preference", "tags": ["café"]},
        ctx,
    )
    assert guardado.ok, guardado.error
    item_id = guardado.data["id"]
    assert item_id

    achado = run("memory_recall", {"query": "café"}, ctx)
    assert achado.ok, achado.error
    assert "café sem açúcar" in achado.content
    assert achado.data and achado.data[0]["id"] == item_id

    apagado = run("memory_forget", {"id": item_id}, ctx)
    assert apagado.ok
    assert run("memory_recall", {"query": "café"}, ctx).content.startswith("nenhuma")


def test_forget_id_inexistente(tmp_path, memoria) -> None:
    set_memory(memoria)
    ctx = make_ctx(tmp_path)
    result = run("memory_forget", {"id": "nao_existe"}, ctx)
    assert result.ok is False
    assert "não encontrada" in (result.error or "")


def test_remember_valida_argumentos(tmp_path, memoria) -> None:
    set_memory(memoria)
    ctx = make_ctx(tmp_path)
    sem_texto = run("memory_remember", {}, ctx)
    assert sem_texto.ok is False and "text" in (sem_texto.error or "")
    vazio = run("memory_remember", {"text": "   "}, ctx)
    assert vazio.ok is False
    kind_ruim = run("memory_remember", {"text": "texto ok", "kind": "coisa"}, ctx)
    assert kind_ruim.ok is False
    assert "kind" in (kind_ruim.error or "")
    assert memoria.count() == 0


def test_recall_valida_argumentos(tmp_path, memoria) -> None:
    set_memory(memoria)
    ctx = make_ctx(tmp_path)
    sem_query = run("memory_recall", {}, ctx)
    assert sem_query.ok is False and "query" in (sem_query.error or "")
    assert run("memory_recall", {"query": "qualquer coisa"}, ctx).ok


def test_recall_limita_k(tmp_path, memoria) -> None:
    set_memory(memoria)
    ctx = make_ctx(tmp_path)
    for index in range(8):
        memoria.remember(f"registro {index} {uuid.uuid4().hex} para teste de k")
    result = run("memory_recall", {"query": "registro", "k": 999}, ctx)
    assert result.ok
    assert len(result.data) <= 20
    resultado_k_ruim = run("memory_recall", {"query": "registro", "k": "abc"}, ctx)
    assert resultado_k_ruim.ok
    assert len(resultado_k_ruim.data) == 5  # k inválido vira o padrão 5


def test_recall_sem_resultado(tmp_path, memoria) -> None:
    set_memory(memoria)
    ctx = make_ctx(tmp_path)
    result = run("memory_recall", {"query": "zqxjpv inexistente"}, ctx)
    assert result.ok
    assert "nenhuma memória" in result.content
    assert result.data == []


def test_tags_como_string_de_virgulas(tmp_path, memoria) -> None:
    set_memory(memoria)
    ctx = make_ctx(tmp_path)
    result = run(
        "memory_remember", {"text": "anotação com tags em string", "tags": "casa, projeto"}, ctx
    )
    assert result.ok, result.error
    assert result.data["tags"] == ["casa", "projeto"]


def test_set_get_memory(memoria) -> None:
    assert get_memory() is None
    set_memory(memoria)
    assert get_memory() is memoria
    set_memory(None)
    assert get_memory() is None
