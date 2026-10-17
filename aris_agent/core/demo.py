"""Demo do núcleo: roda uma tarefa de exemplo com FakeLLM (sem rede, sem LLM real).

Uso::

    python -m aris_agent.core.demo
"""

from __future__ import annotations

import logging
import re
import sys
import tempfile
from pathlib import Path

from ..config import AgentConfig
from ..contract import AgentEvent, Risk, ToolCall, ToolContext, ToolResult, ToolSpec
from ..contract.types import ChatMessage
from ..fakes import AutoConfirm, EchoTool, FakeLLM, FakeMemory, FakeSkills, PassthroughExecutor
from ..tools.registry import ToolRegistry, function_tool
from .agent import ArisAgent

_TAREFA = (
    "chefe, monta um plano de estudo de Python com 3 etapas e calcula quanto tempo "
    "dao 3 blocos de 45 minutos"
)


def _calc():
    """Calculadora minúscula só para o demo (não vai para aris_agent/tools/)."""
    spec = ToolSpec(
        name="calc",
        description="Calcula uma expressao aritmetica simples.",
        parameters={
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
        risk=Risk.READ,
        tags=("calc",),
    )

    @function_tool(spec)
    def calc(args: dict, ctx: ToolContext) -> ToolResult:
        expr = str(args.get("expression", ""))
        if not re.fullmatch(r"[0-9+\-*/(). %]+", expr):
            return ToolResult(ok=False, error="expressao invalida")
        try:
            return ToolResult(ok=True, content=str(eval(expr, {"__builtins__": {}}, {})))  # noqa: S307
        except Exception as exc:  # noqa: BLE001 - demo
            return ToolResult(ok=False, error=f"nao deu para calcular: {exc}")

    return calc


def _roteiro() -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="plan_update",
                    arguments={
                        "items": [
                            {"text": "Definir os blocos de estudo", "status": "doing"},
                            {"text": "Calcular o total de horas", "status": "todo"},
                            {"text": "Resumir o plano para a voz", "status": "todo"},
                        ]
                    },
                )
            ],
        ),
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(id="c2", name="calc", arguments={"expression": "3 * 45"})
            ],
        ),
        ChatMessage(
            role="assistant",
            content=(
                "Fechou, chefe: 3 blocos de 45 minutos dao 2h15 de estudo, e o plano "
                "de 3 etapas ficou salvo na tarefa."
            ),
        ),
    ]


def _mostrar(evento: AgentEvent) -> None:
    partes = [f"{chave}={valor!r}" for chave, valor in list(evento.data.items())[:3]]
    print(f"  [{evento.type}] {' '.join(partes)}")


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s", force=True
    )
    base = Path(tempfile.gettempdir()) / "aris_core_demo"
    cfg = AgentConfig(
        workspace_dir=base / "workspace",
        data_dir=base / "dados",
        max_steps=8,
        sections={"core": {"max_context_tokens": 4000}},
    )

    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(_calc())

    llm = FakeLLM(_roteiro())
    memoria = FakeMemory()
    skills = FakeSkills({"relatorio": ("gera um relatorio curto", "use plan_update e responda curto")})
    agente = ArisAgent(llm, PassthroughExecutor(registry), registry, memoria, skills, cfg)

    print(f"Tarefa: {_TAREFA}")
    print("Eventos:")
    resultado = agente.run(_TAREFA, "demo", AutoConfirm(True), events=_mostrar)

    print(
        f"\nResultado: ok={resultado.ok} motivo={resultado.stopped_reason} "
        f"passos={resultado.steps} chamadas={resultado.tool_calls} "
        f"tokens={resultado.usage.prompt_tokens}/{resultado.usage.completion_tokens}"
    )
    print(f"Resposta: {resultado.text}")
    trace = cfg.data_dir / "traces" / f"{resultado.trace_id}.jsonl"
    print(f"Trace: {trace}")
    if trace.is_file():
        linhas = trace.read_text(encoding="utf-8").splitlines()
        print(f"Linhas do trace ({len(linhas)}):")
        for linha in linhas:
            print(f"  {linha[:160]}")
    print(f"Turnos na memoria: {len(memoria.recent_turns('demo', 10))}")
    return 0 if resultado.ok else 1


if __name__ == "__main__":
    sys.exit(main())
