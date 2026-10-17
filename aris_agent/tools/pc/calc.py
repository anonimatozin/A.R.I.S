"""Calculadora segura por AST — sem ``eval``, sem atributos, sem import dinâmico."""

from __future__ import annotations

import ast
import logging
import math
from collections.abc import Callable

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ..registry import function_tool
from .helpers import err, guarded, ok_result, schema

log = logging.getLogger("aris.agent.tools.pc.calc")

SPEC_CALC = ToolSpec(
    name="calc",
    description="Calcula uma expressão matemática com segurança (AST, sem eval). Ex.: 2*(3+4), sqrt(25).",
    parameters=schema(
        {
            "expression": {
                "type": "string",
                "description": "Expressão aritmética, ex.: sqrt(2) * 100 / 3.",
            }
        },
        required=("expression",),
    ),
    risk=Risk.READ,
    tags=("pc", "calc"),
    timeout_s=5.0,
)

_MAX_EXPRESSION_CHARS = 500
_MAX_NODES = 200
_MAX_EXPONENT = 10_000
_MAX_BITS = 400_000

_FUNCTIONS: dict[str, Callable] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "degrees": math.degrees,
    "radians": math.radians,
    "hypot": math.hypot,
    "trunc": math.trunc,
}

_CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e, "tau": math.tau}

_BIN_OPS: dict[type, Callable] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}

_UNARY_OPS: dict[type, Callable] = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
    ast.Not: lambda a: not a,
}

_CMP_OPS: dict[type, Callable] = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}


class CalcError(ValueError):
    """Expressão recusada ou erro de cálculo (vira ToolResult)."""


def _check_node(node: ast.AST) -> None:
    """Rejeita qualquer nó fora do conjunto mínimo de uma calculadora."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or isinstance(node.value, (int, float, complex)):
            return
        raise CalcError(f"constante {node.value!r} não é numérica")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        return
    if isinstance(node, ast.Compare) and all(type(op) in _CMP_OPS for op in node.ops):
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise CalcError("função não permitida (use sqrt, log, min, max, round, ...)")
        if node.keywords:
            raise CalcError("argumentos nomeados não são permitidos")
        return
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return
        raise CalcError(f"nome não permitido: {node.id!r}")
    if isinstance(node, ast.List):
        return
    if isinstance(node, ast.IfExp):
        raise CalcError("expressão condicional (a if b else c) não é permitida")
    raise CalcError(f"construção não permitida: {type(node).__name__}")


def _walk_check(node: ast.AST, budget: list[int]) -> None:
    """Percorre a árvore aplicando as regras, descendo só nos operandos de valor."""
    budget[0] += 1
    if budget[0] > _MAX_NODES:
        raise CalcError(f"expressão grande demais (máx {_MAX_NODES} nós)")
    _check_node(node)
    if isinstance(node, ast.BinOp):
        _walk_check(node.left, budget)
        _walk_check(node.right, budget)
    elif isinstance(node, ast.UnaryOp):
        _walk_check(node.operand, budget)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            _walk_check(value, budget)
    elif isinstance(node, ast.Compare):
        _walk_check(node.left, budget)
        for comparator in node.comparators:
            _walk_check(comparator, budget)
    elif isinstance(node, ast.Call):
        for argument in node.args:
            _walk_check(argument, budget)
    elif isinstance(node, ast.List):
        for item in node.elts:
            _walk_check(item, budget)
    elif isinstance(node, (ast.Constant, ast.Name)):
        return
    else:  # pragma: no cover - _check_node já rejeitou o que não é isto
        for child in ast.iter_child_nodes(node):
            _walk_check(child, budget)


def _evaluate(node: ast.AST):
    """Avalia o nó já validado; só operações aritméticas de números."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            _guard_pow(left, right)
        try:
            return _BIN_OPS[type(node.op)](left, right)
        except ZeroDivisionError:
            raise CalcError("divisão por zero") from None
        except (OverflowError, ValueError) as exc:
            raise CalcError(f"erro de cálculo: {exc}") from None
    if isinstance(node, ast.UnaryOp):
        return _UNARY_OPS[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.BoolOp):
        values = [_evaluate(v) for v in node.values]
        if isinstance(node.op, ast.And):
            result = True
            for value in values:
                result = value
                if not value:
                    break
            return result
        result = False
        for value in values:
            result = value
            if value:
                break
        return result
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _evaluate(comparator)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)
        func = _FUNCTIONS[node.func.id]
        args = [_evaluate(arg) for arg in node.args]
        try:
            return func(*args)
        except ZeroDivisionError:
            raise CalcError("divisão por zero") from None
        except (ValueError, TypeError, OverflowError) as exc:
            raise CalcError(f"erro em {node.func.id}(): {exc}") from None
    if isinstance(node, ast.Name):
        assert isinstance(node.id, str)
        return _CONSTANTS[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_evaluate(item) for item in node.elts]
    raise CalcError(f"não sei avaliar {type(node).__name__}")  # pragma: no cover - defensivo

def _guard_pow(base, exponent) -> None:
    """Impede ``9**9**9`` e companhia de travar a máquina."""
    if isinstance(exponent, int) and not isinstance(exponent, bool) and abs(exponent) > _MAX_EXPONENT:
        raise CalcError(f"expoente grande demais (máx {_MAX_EXPONENT})")
    if isinstance(base, int) and isinstance(exponent, int) and exponent > 0:
        estimated = max(1, base.bit_length()) * exponent
        if estimated > _MAX_BITS:
            raise CalcError("resultado seria grande demais")


def _format(value) -> str:
    if isinstance(value, bool):
        return "verdadeiro" if value else "falso"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value == math.inf:
            return "inf"
        if value == -math.inf:
            return "-inf"
        if value.is_integer():
            return f"{value:.1f}"
        return repr(round(value, 12))
    if isinstance(value, complex):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format(item) for item in value) + "]"
    return str(value)  # pragma: no cover - defensivo


@function_tool(SPEC_CALC)
@guarded
def calc(args: dict, ctx: ToolContext) -> ToolResult:
    """Avalia a expressão por AST restrito e devolve o resultado formatado."""
    expression = args.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        return err("expression vazia")
    expression = expression.strip()
    if len(expression) > _MAX_EXPRESSION_CHARS:
        return err(f"expressão longa demais ({len(expression)} > {_MAX_EXPRESSION_CHARS} caracteres)")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return err(f"expressão inválida: {exc.msg}")
    try:
        _walk_check(tree.body, [1])
        value = _evaluate(tree.body)
    except CalcError as exc:
        log.debug("calc recusou %r: %s", expression, exc)
        return err(str(exc))
    if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > _MAX_BITS:
        return err("resultado inteiro grande demais")
    if isinstance(value, int) and not isinstance(value, bool) and _int_digits(value) > 4000:
        return err(f"resultado inteiro com {_int_digits(value)} dígitos; muito grande para exibir")
    try:
        text = _format(value)
    except ValueError:
        return err("resultado grande demais para exibir")
    log.debug("calc: %s = %s", expression, text)
    return ok_result(text, data={"result": value if isinstance(value, (int, float, complex)) else None})


def _int_digits(value: int) -> int:
    """Estimativa de dígitos de um inteiro sem chamar ``str()`` (limite de 4300 no 3.12)."""
    if value == 0:
        return 1
    return int(abs(value).bit_length() * 0.30103) + 1
