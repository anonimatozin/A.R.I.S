"""Testes do registro de ferramentas (Parte 0)."""

from __future__ import annotations

import threading

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.errors import ToolError
from aris_agent.contract.types import Risk, ToolContext, ToolResult, ToolSpec
from aris_agent.fakes import EchoTool
from aris_agent.tools import ToolRegistry, function_tool


def make_ctx(tmp_path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(
        session_id="s1", workdir=tmp_path, config=cfg, cancel=threading.Event()
    )


def spec(name: str = "ferramenta_x", **kwargs) -> ToolSpec:
    kwargs.setdefault("risk", Risk.READ)
    kwargs.setdefault("description", "...")
    kwargs.setdefault("parameters", {"type": "object", "properties": {}})
    return ToolSpec(name=name, **kwargs)


def test_registro_basico() -> None:
    reg = ToolRegistry()
    tool = EchoTool()
    reg.register(tool)
    assert "echo" in reg
    assert reg.get("echo") is tool
    assert len(reg) == 1
    assert reg.all() == [tool]
    assert reg.specs() == [tool.spec]


def test_registro_duplicado_levanta_erro() -> None:
    reg = ToolRegistry()
    reg.register(EchoTool())
    with pytest.raises(ToolError, match="já registrada"):
        reg.register(EchoTool())


def test_get_desconhecido_levanta_erro() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolError, match="desconhecida"):
        reg.get("nao_existe")
    assert "nao_existe" not in reg


def test_registro_objeto_invalido() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolError):
        reg.register(object())
    with pytest.raises(ToolError):
        reg.register(EchoTool().run)  # sem atributo .spec


def test_spec_sem_nome() -> None:
    reg = ToolRegistry()

    class Fake:
        spec = ToolSpec(name="", description="", parameters={}, risk=Risk.READ)

        def run(self, args, ctx):  # pragma: no cover
            return ToolResult(ok=True, content="")

    with pytest.raises(ToolError, match="sem nome"):
        reg.register(Fake())


def test_specs_filtrados_por_tags() -> None:
    reg = ToolRegistry()

    class Tool:
        def __init__(self, s: ToolSpec) -> None:
            self.spec = s

        def run(self, args, ctx):  # pragma: no cover
            return ToolResult(ok=True, content="")

    reg.register(Tool(spec("a", tags=("pc", "files"))))
    reg.register(Tool(spec("b", tags=("web",))))
    reg.register(Tool(spec("c", tags=("pc", "web"))))
    assert [s.name for s in reg.specs(("pc",))] == ["a", "c"]
    assert [s.name for s in reg.specs(("pc", "web"))] == ["c"]
    assert [s.name for s in reg.specs()] == ["a", "b", "c"]


def test_path_args_ausentes_só_avisa(caplog) -> None:
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(
        _Tool(spec("com_caminho", path_args=("caminho",), parameters={"type": "object"}))
    )
    assert any("caminho" in r.message for r in caplog.records)


def _Tool(s: ToolSpec):  # noqa: N802 - helper local
    class _T:
        spec = s

        def run(self, args, ctx):  # pragma: no cover
            return ToolResult(ok=True, content="")

    return _T()


def test_function_tool_devolve_resultado(tmp_path) -> None:
    @function_tool(spec("soma"))
    def soma(args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, content=str(args["a"] + args["b"]))

    reg = ToolRegistry()
    reg.register(soma)
    tool = reg.get("soma")
    result = tool.run({"a": 2, "b": 3}, make_ctx(tmp_path))  # type: ignore[attr-defined]
    assert result.ok and result.content == "5"


def test_function_tool_converte_excecao(tmp_path) -> None:
    @function_tool(spec("explode"))
    def explode(args: dict, ctx: ToolContext) -> ToolResult:
        raise RuntimeError("deu ruim")

    result = explode.run({}, make_ctx(tmp_path))
    assert result.ok is False
    assert "RuntimeError" in (result.error or "")


def test_function_tool_tipo_invalido(tmp_path, caplog) -> None:
    @function_tool(spec("errada"))
    def errada(args: dict, ctx: ToolContext):  # type: ignore[misc]
        return "não sou ToolResult"

    result = errada.run({}, make_ctx(tmp_path))
    assert result.ok is False
    assert "inválido" in (result.error or "")


def test_function_tool_fora_da_funcao() -> None:
    with pytest.raises(ToolError):
        function_tool(spec("x"))("não é função")  # type: ignore[operator]


def test_registry_com_iteravel_inicial() -> None:
    reg = ToolRegistry([EchoTool()])
    assert "echo" in reg
