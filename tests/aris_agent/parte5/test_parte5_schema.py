"""Validação de schema dos argumentos (Parte 5)."""

from __future__ import annotations

from test_parte5_helpers import (  # noqa: F421 - import irmão (mesmo diretório)
    RecordingTool,
    audit_events,
    make_config,
    make_ctx,
    make_executor,
    spec,
    tool_call,
)

from aris_agent.fakes import AutoConfirm

SCHEMA = {
    "type": "object",
    "properties": {
        "nome": {"type": "string"},
        "quantidade": {"type": "integer", "minimum": 1, "maximum": 10},
        "modo": {"type": "string", "enum": ["a", "b"]},
    },
    "required": ["nome"],
    "additionalProperties": False,
}


def _tool(**kwargs) -> RecordingTool:
    return RecordingTool(spec("esquema", parameters=SCHEMA, **kwargs))


def test_argumento_ausente(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    result = executor.execute(tool_call("esquema", {"quantidade": 2}), make_ctx(config), AutoConfirm())
    assert result.ok is False
    assert "argumento ausente: nome" in (result.error or "")
    assert tool.calls == []


def test_tipo_errado(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    result = executor.execute(tool_call("esquema", {"nome": 42}), make_ctx(config), AutoConfirm())
    assert result.ok is False
    assert "tipo errado" in (result.error or "")
    assert "string" in (result.error or "")
    assert tool.calls == []


def test_campo_extra_negado(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    result = executor.execute(
        tool_call("esquema", {"nome": "x", "sobrenome": "y"}), make_ctx(config), AutoConfirm()
    )
    assert result.ok is False
    assert "campo não permitido: sobrenome" in (result.error or "")
    assert tool.calls == []


def test_enum_invalido(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    result = executor.execute(
        tool_call("esquema", {"nome": "x", "modo": "z"}), make_ctx(config), AutoConfirm()
    )
    assert result.ok is False
    assert "valor inválido" in (result.error or "")


def test_min_max(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    result = executor.execute(
        tool_call("esquema", {"nome": "x", "quantidade": 99}), make_ctx(config), AutoConfirm()
    )
    assert result.ok is False
    assert "maior que o máximo" in (result.error or "")


def test_argumentos_validos_executam(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    result = executor.execute(
        tool_call("esquema", {"nome": "aris", "quantidade": 3}), make_ctx(config), AutoConfirm()
    )
    assert result.ok is True
    assert tool.calls == [{"nome": "aris", "quantidade": 3}]


def test_argumentos_nao_objeto(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    result = executor.execute(tool_call("esquema", ["nao", "e", "dict"]), make_ctx(config), AutoConfirm())  # type: ignore[arg-type]
    assert result.ok is False
    assert "objeto JSON" in (result.error or "")
    assert tool.calls == []


def test_ferramenta_desconhecida(tmp_path) -> None:
    config = make_config(tmp_path)
    executor = make_executor(config, [])
    result = executor.execute(tool_call("nao_existe"), make_ctx(config), AutoConfirm())
    assert result.ok is False
    assert "desconhecida" in (result.error or "")


def test_falha_de_schema_vai_para_auditoria(tmp_path) -> None:
    config = make_config(tmp_path)
    executor = make_executor(config, [_tool()])
    executor.execute(tool_call("esquema", {}), make_ctx(config), AutoConfirm())
    eventos = audit_events(config)
    assert eventos[-1]["decision"] == "deny"
    assert eventos[-1]["reason"] == "validação de schema"
    assert eventos[-1]["ok"] is False
