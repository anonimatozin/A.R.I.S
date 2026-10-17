"""Utilitários compartilhados dos testes da Parte 5.

Arquivo casa com ``test_*`` mas não define testes: só dublês e builders
(ferramentas falsas com ``ToolSpec`` configurável; nada aqui executa de
verdade comandos destrutivos).
"""

from __future__ import annotations

import json
import threading
import time

from aris_agent.config import AgentConfig
from aris_agent.contract.types import Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from aris_agent.safety import SafeExecutor
from aris_agent.tools import ToolRegistry


def make_config(tmp_path, **safety) -> AgentConfig:
    """Config com workspace/data em tmp_path e a seção ``safety`` informada."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return AgentConfig(
        workspace_dir=workspace,
        data_dir=tmp_path / "data",
        sections={"safety": dict(safety)},
    )


def make_ctx(config: AgentConfig, *, taint: bool = False, session_id: str = "s1") -> ToolContext:
    return ToolContext(
        session_id=session_id,
        workdir=config.workspace_dir,
        config=config,
        cancel=threading.Event(),
        taint=taint,
    )


def spec(name: str = "ferramenta", *, risk: Risk = Risk.READ, **kwargs) -> ToolSpec:
    kwargs.setdefault("description", "ferramenta de teste")
    kwargs.setdefault("parameters", {"type": "object", "properties": {}})
    return ToolSpec(name=name, risk=risk, **kwargs)


class RecordingTool:
    """Ferramenta falsa: registra cada chamada e devolve o configurado."""

    def __init__(
        self,
        tool_spec: ToolSpec,
        *,
        content: str = "ok",
        ok: bool = True,
        error: str | None = None,
        delay: float = 0.0,
        boom: BaseException | None = None,
        result_fn=None,
        artifacts: list | None = None,
    ) -> None:
        self.spec = tool_spec
        self.calls: list[dict] = []
        self._content = content
        self._ok = ok
        self._error = error
        self._delay = delay
        self._boom = boom
        self._result_fn = result_fn
        self._artifacts = artifacts or []

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        self.calls.append(dict(args))
        if self._delay:
            time.sleep(self._delay)
        if self._boom is not None:
            raise self._boom
        if self._result_fn is not None:
            return self._result_fn(args, ctx)
        if self._ok:
            return ToolResult(ok=True, content=str(self._content), artifacts=list(self._artifacts))
        return ToolResult(ok=False, error=str(self._error or "falhou"))


def make_executor(config: AgentConfig, tools=(), **kwargs) -> SafeExecutor:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return SafeExecutor(registry, config, **kwargs)


def tool_call(name: str, arguments: dict | None = None) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=arguments if arguments is not None else {})


def audit_events(config: AgentConfig) -> list[dict]:
    """Lê o JSONL de auditoria da config (lista vazia se não existir)."""
    path = config.audit_log_path
    if path is None or not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events
