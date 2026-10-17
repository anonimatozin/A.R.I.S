"""Plugin de exemplo: Calculator

Demonstra como criar um plugin para o A.R.I.S.
Plugin simples que avalia expressões matemáticas de forma segura
(sem ``eval``).

Para instalar: coloque este arquivo em plugins/
O A.R.I.S. carrega automaticamente no próximo start.
"""

import ast
import operator

# Avaliador aritmético seguro (sem eval): apenas números e operadores.
_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}

_UNOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval(expression: str) -> float:
    """Avalia uma expressão aritmética sem executar código arbitrário.

    Constrói a árvore sintática e só aceita constantes numéricas,
    operadores binários e operadores unários. Nunca executa chamadas,
    atribuições ou nomes.
    """
    tree = ast.parse(expression, mode="eval")

    def _eval_node(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNOPS:
            return _UNOPS[type(node.op)](_eval_node(node.operand))
        raise ValueError("expressão não suportada")

    result = _eval_node(tree.body)
    if isinstance(result, complex):
        raise ValueError("expressão não suportada")
    return result


def handle_calc(action: str, params: dict, **ctx) -> str:
    """Handler do comando calc."""
    expression = params.get("expression", params.get("query", ""))
    if not expression:
        return "Forneça uma expressão. Ex: calc 2+2"

    # Sanitizar: apenas caracteres matemáticos
    allowed = set("0123456789+-*/.().% ")
    if not all(c in allowed for c in expression):
        return "Expressão contém caracteres inválidos."

    try:
        result = _safe_eval(expression)
        print(f"  {expression} = {result}")
        return str(result)
    except Exception as e:
        return f"Erro ao calcular: {e}"


def register(registry):
    """Auto-registra o plugin no registry."""
    registry.register_intent(
        "calc",
        description="Calculadora de expressões matemáticas"
    )
    # Substituir handler genérico pelo nosso
    registry._intent_handlers["calc"] = handle_calc
