"""Testes da calculadora segura por AST (Parte 2)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.types import ToolContext
from aris_agent.tools import ToolRegistry
from aris_agent.tools import pc as pacote_pc


def make_ctx(tmp_path: Path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(session_id="s", workdir=tmp_path, config=cfg, cancel=threading.Event())


def calc(registry: ToolRegistry, ctx: ToolContext, expression: str):
    return registry.get("calc").run({"expression": expression}, ctx)


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    pacote_pc.register(reg)
    return reg


@pytest.mark.parametrize(
    ("expression", "esperado"),
    [
        ("2 + 3 * 4", "14"),
        ("(2 + 3) * 4", "20"),
        ("10 / 4", "2.5"),
        ("7 // 2", "3"),
        ("7 % 3", "1"),
        ("2**10", "1024"),
        ("-5 + 3", "-2"),
        ("abs(-7)", "7"),
        ("round(3.14159, 2)", "3.14"),
        ("min(4, 7, 1)", "1"),
        ("max(4, 7, 1)", "7"),
        ("sum([1, 2, 3])", "6"),
        ("sqrt(16)", "4.0"),
        ("log10(1000)", "3.0"),
        ("floor(2.7)", "2"),
        ("ceil(2.1)", "3"),
        ("hypot(3, 4)", "5.0"),
        ("2 > 1", "verdadeiro"),
        ("3 < 2", "falso"),
        ("1 == 1 and 2 == 2", "verdadeiro"),
        ("not False", "verdadeiro"),
        ("pi", "3.14159265359"),
    ],
)
def test_expressoes_validas(tmp_path, registry, expression, esperado) -> None:
    result = calc(registry, make_ctx(tmp_path), expression)
    assert result.ok, f"{expression}: {result.error}"
    assert result.content == esperado


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('calc')",
        "__import__('os')",
        "().__class__",
        "(1).__class__.__bases__",
        "open('arquivo')",
        "lambda: 1",
        "[x for x in range(10)]",
        "exec('print(1)')",
        "eval('1+1')",
        "globals()",
        "os.system('ls')",
        "x",
        "foo",
        "'string'",
        "b'bytes'",
        "1 if True else 2",
        "a if b else c",
        "def f(): pass",
        "x = 5",
        "getattr(int, 'x')",
        "[].append(1)",
        "{'a': 1}",
        "1, 2",
    ],
)
def test_injecoes_e_construcoes_recusadas(tmp_path, registry, expression) -> None:
    result = calc(registry, make_ctx(tmp_path), expression)
    assert not result.ok, f"deveria recusar {expression!r}"
    assert result.error


def test_divisao_por_zero(tmp_path, registry) -> None:
    result = calc(registry, make_ctx(tmp_path), "1/0")
    assert not result.ok
    assert "divisão por zero" in (result.error or "")


def test_expoente_grande_recusado(tmp_path, registry) -> None:
    result = calc(registry, make_ctx(tmp_path), "2**999999999")
    assert not result.ok
    assert "expoente" in (result.error or "")


def test_potencia_aninhada_recusada(tmp_path, registry) -> None:
    result = calc(registry, make_ctx(tmp_path), "2 ** (9 ** 9)")
    assert not result.ok


def test_resultado_com_muitos_digitos_recusado(tmp_path, registry) -> None:
    result = calc(registry, make_ctx(tmp_path), "9**9999")
    assert not result.ok
    assert "dígito" in (result.error or "")


def test_funcao_fora_da_lista_recusada(tmp_path, registry) -> None:
    result = calc(registry, make_ctx(tmp_path), "pow(2, 10)")
    assert not result.ok
    assert "função não permitida" in (result.error or "")


def test_expressao_longa_recusada(tmp_path, registry) -> None:
    result = calc(registry, make_ctx(tmp_path), "1+" * 400 + "1")
    assert not result.ok
    assert "longa demais" in (result.error or "")


def test_sintaxe_invalida(tmp_path, registry) -> None:
    result = calc(registry, make_ctx(tmp_path), "2**")
    assert not result.ok
    assert "inválida" in (result.error or "")


def test_expression_vazia_ou_nao_string(tmp_path, registry) -> None:
    ctx = make_ctx(tmp_path)
    assert not registry.get("calc").run({"expression": "  "}, ctx).ok
    assert not registry.get("calc").run({"expression": 42}, ctx).ok
    assert not registry.get("calc").run({}, ctx).ok
