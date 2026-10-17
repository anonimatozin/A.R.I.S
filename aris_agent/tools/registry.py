"""Registro de ferramentas. Não alterar sem pedido em docs/agent/pedidos/."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from ..contract.errors import ToolError
from ..contract.types import ToolContext, ToolResult, ToolSpec

log = logging.getLogger("aris.agent.tools.registry")

ToolFn = Callable[[dict, ToolContext], ToolResult]


class FunctionTool:
    """Ferramenta construída a partir de uma função ``(args, ctx) -> ToolResult``.

    Qualquer exceção vira ``ToolResult(ok=False)``: nada escapa para o laço do agente.
    """

    def __init__(self, spec: ToolSpec, fn: ToolFn) -> None:
        self.spec = spec
        self._fn = fn

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        try:
            result = self._fn(args, ctx)
        except Exception as exc:  # noqa: BLE001 - ferramenta não pode derrubar o laço
            log.exception("ferramenta %s lançou exceção", self.spec.name)
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        if not isinstance(result, ToolResult):
            log.error("ferramenta %s devolveu %s em vez de ToolResult", self.spec.name, type(result))
            return ToolResult(ok=False, error="ferramenta devolveu um tipo inválido")
        return result

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"<FunctionTool {self.spec.name}>"


def _validate_spec(spec: ToolSpec) -> None:
    if not isinstance(spec, ToolSpec):
        raise ToolError(f"spec inválida: esperado ToolSpec, veio {type(spec).__name__}")
    if not spec.name or not str(spec.name).strip():
        raise ToolError("ferramenta sem nome")
    if not isinstance(spec.parameters, dict):
        raise ToolError(f"ferramenta {spec.name}: parameters precisa ser dict (JSON Schema)")
    if spec.parameters and spec.parameters.get("type") != "object":
        log.warning("ferramenta %s: JSON Schema sem type=object", spec.name)
    for arg in (*spec.path_args, *spec.url_args):
        if arg not in spec.parameters.get("properties", {}):
            log.warning("ferramenta %s: parâmetro %r declarado mas ausente no schema", spec.name, arg)
    if spec.command_arg and spec.command_arg not in spec.parameters.get("properties", {}):
        log.warning(
            "ferramenta %s: command_arg %r ausente no schema", spec.name, spec.command_arg
        )


class ToolRegistry:
    """Conjunto de ferramentas por nome. Nomes são únicos."""

    def __init__(self, tools: Iterable[ToolSpec | FunctionTool | object] = ()) -> None:
        self._tools: dict[str, object] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: object) -> object:
        """Registra uma ferramenta; levanta ``ToolError`` se o nome já existir."""
        spec = getattr(tool, "spec", None)
        if not isinstance(spec, ToolSpec) or not callable(getattr(tool, "run", None)):
            raise ToolError(f"objeto inválido para registro: {tool!r}")
        _validate_spec(spec)
        if spec.name in self._tools:
            raise ToolError(f"ferramenta já registrada: {spec.name}")
        self._tools[spec.name] = tool
        log.debug("ferramenta registrada: %s", spec.name)
        return tool

    def get(self, name: str) -> object:
        """Devolve a ferramenta pelo nome ou levanta ``ToolError``."""
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(f"ferramenta desconhecida: {name}") from None

    def all(self) -> list[object]:
        """Todas as ferramentas, na ordem de registro."""
        return list(self._tools.values())

    def specs(self, tags: tuple | None = None) -> list[ToolSpec]:
        """Especificações, opcionalmente filtradas por ``tags`` (interseção)."""
        out: list[ToolSpec] = []
        for tool in self._tools.values():
            spec = tool.spec  # type: ignore[attr-defined]
            if tags is None or set(tags).issubset(set(spec.tags)):
                out.append(spec)
        return out

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"<ToolRegistry {sorted(self._tools)}>"


def function_tool(spec: ToolSpec) -> Callable[[ToolFn], FunctionTool]:
    """Decora/fabrica uma ``Tool`` a partir de uma função ``(args, ctx) -> ToolResult``.

    Uso::

        @function_tool(ToolSpec(name="soma", ...))
        def soma(args, ctx):
            return ToolResult(ok=True, content=str(...))
    """

    def deco(fn: ToolFn) -> FunctionTool:
        if not callable(fn):
            raise ToolError("function_tool espera uma função")
        return FunctionTool(spec, fn)

    return deco
