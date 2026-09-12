"""Plugin de exemplo: Calculator

Demonstra como criar um plugin para o A.R.I.S.
Plugin simples que avalia expressões matemáticas.

Para instalar: coloque este arquivo em plugins/
O A.R.I.S. carrega automaticamente no próximo start.
"""

from core.commands import registry


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
        result = eval(expression)  # noqa: S307 — sandbox limitado
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
