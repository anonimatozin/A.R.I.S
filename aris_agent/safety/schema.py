"""Validação de argumentos contra o JSON Schema do ``ToolSpec`` (subconjunto útil).

Coberto: ``type``, ``required``, ``properties``, ``additionalProperties=False``,
``enum``, ``minimum``/``maximum``, ``minLength``/``maxLength``, ``items``.
Mensagens em pt-BR para o modelo corrigir a chamada.
"""

from __future__ import annotations

from typing import Any

_TYPE_MAP: tuple[tuple[str, type | tuple[type, ...]], ...] = (
    ("string", str),
    ("boolean", bool),
    ("integer", int),
    ("number", (int, float)),
    ("array", list),
    ("object", dict),
    ("null", type(None)),
)


def _type_ok(expected: str, value: Any) -> bool:
    for name, py_type in _TYPE_MAP:
        if name == expected:
            if expected in ("integer", "number") and isinstance(value, bool):
                return False
            if expected == "boolean" and not isinstance(value, bool):
                return False
            return isinstance(value, py_type)
    return True  # tipo desconhecido no schema: não barramos


def _check_value(prop: dict, value: Any, label: str) -> list[str]:
    errors: list[str] = []
    expected = prop.get("type")
    if isinstance(expected, str) and not _type_ok(expected, value):
        errors.append(f"argumento {label}: tipo errado (esperado {expected}, veio {type(value).__name__})")
        return errors
    if "enum" in prop and value not in prop["enum"]:
        errors.append(f"argumento {label}: valor inválido {value!r} (esperado um de {prop['enum']})")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in prop and value < prop["minimum"]:
            errors.append(f"argumento {label}: {value} menor que o mínimo {prop['minimum']}")
        if "maximum" in prop and value > prop["maximum"]:
            errors.append(f"argumento {label}: {value} maior que o máximo {prop['maximum']}")
    if isinstance(value, str):
        if "minLength" in prop and len(value) < prop["minLength"]:
            errors.append(f"argumento {label}: texto curto demais (mínimo {prop['minLength']})")
        if "maxLength" in prop and len(value) > prop["maxLength"]:
            errors.append(f"argumento {label}: texto longo demais (máximo {prop['maxLength']})")
    if isinstance(value, list) and isinstance(prop.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(_check_value(prop["items"], item, f"{label}[{index}]"))
    if isinstance(value, dict) and isinstance(prop.get("properties"), dict):
        nested = validate_object(prop, value)
        errors.extend(f"{label}.{e}" if not e.startswith("argumento") else e for e in nested)
    return errors


def validate_object(schema: dict, args: dict) -> list[str]:
    """Valida ``args`` contra um JSON Schema ``type=object``; devolve a lista de erros."""
    if not isinstance(schema, dict):
        return []
    errors: list[str] = []
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    required = schema.get("required") or []

    for name in required:
        if name not in args:
            errors.append(f"argumento ausente: {name}")

    additional = schema.get("additionalProperties", True)
    for key, value in args.items():
        if key not in properties:
            if additional is False:
                errors.append(f"campo não permitido: {key}")
            elif isinstance(additional, dict):
                errors.extend(_check_value(additional, value, str(key)))
            continue
        prop = properties.get(key)
        if isinstance(prop, dict):
            errors.extend(_check_value(prop, value, str(key)))
    return errors


def validate_args(parameters: dict, arguments: dict) -> str | None:
    """Valida ``arguments`` contra o schema ``parameters``; ``None`` se estiver válido."""
    if not isinstance(arguments, dict):
        return "argumentos inválidos: esperado um objeto JSON"
    if not isinstance(parameters, dict) or not parameters:
        return None
    errors = validate_object(parameters, arguments)
    if not errors:
        return None
    return "; ".join(errors[:5]) + ("; ..." if len(errors) > 5 else "")
