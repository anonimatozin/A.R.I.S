"""Validação leve de argumentos contra o JSON Schema da ferramenta (Parte 7)."""

from __future__ import annotations

from ..contract.types import ToolSpec


def _matches(value: object, tipo: str) -> bool:
    """Confere o tipo JSON de ``value`` (bool não vale como integer/number)."""
    if tipo == "string":
        return isinstance(value, str)
    if tipo == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if tipo == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if tipo == "boolean":
        return isinstance(value, bool)
    if tipo == "array":
        return isinstance(value, list)
    if tipo == "object":
        return isinstance(value, dict)
    if tipo == "null":
        return value is None
    return True  # tipo desconhecido ao JSON Schema: não barra


def _check(key: str, value: object, schema: object) -> str | None:
    """Devolve mensagem de erro em pt-BR ou ``None`` se o valor estiver válido."""
    if not isinstance(schema, dict):
        return None
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return f"{key}: valor inválido {value!r}; use um de {enum}"
    tipo = schema.get("type")
    if not isinstance(tipo, str):
        return None
    if not _matches(value, tipo):
        return f"{key}: esperado {tipo}, recebido {type(value).__name__}"
    if tipo == "array" and isinstance(schema.get("items"), dict) and isinstance(value, list):
        for index, item in enumerate(value):
            erro = _check(f"{key}[{index}]", item, schema["items"])
            if erro:
                return erro
    if tipo == "object" and isinstance(value, dict):
        sub_required = schema.get("required")
        if isinstance(sub_required, list):
            faltando = [str(r) for r in sub_required if r not in value]
            if faltando:
                return f"{key}: argumento(s) obrigatório(s) ausente(s): " + ", ".join(faltando)
        sub_props = schema.get("properties")
        if isinstance(sub_props, dict):
            for sub_key, sub_value in value.items():
                if sub_key in sub_props:
                    erro = _check(f"{key}.{sub_key}", sub_value, sub_props[sub_key])
                    if erro:
                        return erro
                elif schema.get("additionalProperties") is False:
                    return f"{key}: argumento desconhecido: {sub_key}"
    return None


def validate_args(spec: ToolSpec, args: object) -> str | None:
    """Valida ``args`` contra ``spec.parameters``; devolve erro em pt-BR ou ``None``.

    Só valida o subconjunto que o laço precisa (tipo, required, enum,
    additionalProperties) — a política de segurança é da Parte 5.
    """
    if not isinstance(args, dict):
        return f"argumentos precisam ser um objeto JSON, veio {type(args).__name__}"
    schema = spec.parameters
    if not isinstance(schema, dict) or schema.get("type", "object") != "object":
        return None
    props = schema.get("properties")
    props = props if isinstance(props, dict) else {}
    required = schema.get("required")
    required = required if isinstance(required, list) else []
    missing = [str(r) for r in required if r not in args]
    if missing:
        return "argumento(s) obrigatório(s) ausente(s): " + ", ".join(missing)
    for key, value in args.items():
        if key in props:
            erro = _check(str(key), value, props[key])
            if erro:
                return erro
        elif schema.get("additionalProperties") is False:
            return f"argumento desconhecido: {key}"
    return None


__all__ = ["validate_args"]
