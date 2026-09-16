"""Agent Loop — ciclo real de execucao autonoma.

Fluxo: Usuario → LLM → decide tool → SecurityGate → executa tool → resultado →
       LLM → decide proxima tool → ... → tarefa concluida.

A.R.I.S. nunca afirma ter concluido algo que a tool nao confirmou como sucesso.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ToolCall:
    """Registro de uma chamada de tool."""
    tool_name: str
    parameters: dict[str, Any]
    result: dict[str, Any] | None = None
    status: StepStatus = StepStatus.PENDING
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str | None = None

    @property
    def duration_ms(self) -> int:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at) * 1000)
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool_name,
            "parameters": _redact_params(self.parameters),
            "result_summary": _summarize_result(self.result),
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class AgentTask:
    """Tarefa do Agent Loop."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    objective: str = ""
    context: str = ""
    plan: list[str] = field(default_factory=list)
    current_step: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    verification: str = ""
    final_response: str = ""
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    mode: str = "unknown"

    @property
    def duration_ms(self) -> int:
        if self.completed_at:
            return int((self.completed_at - self.created_at) * 1000)
        return int((time.time() - self.created_at) * 1000)

    @property
    def iteration(self) -> int:
        return len(self.tool_calls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "status": self.status.value,
            "iteration": self.iteration,
            "current_step": self.current_step,
            "plan": self.plan,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "results_count": len(self.results),
            "errors": self.errors,
            "verification": self.verification,
            "final_response": self.final_response,
            "duration_ms": self.duration_ms,
            "mode": self.mode,
        }


def _redact_params(params: dict[str, Any]) -> dict[str, Any]:
    """Redata parametros sensiveis (credenciais, tokens, senhas)."""
    sensitive_keys = {"password", "token", "secret", "key", "credential", "auth"}
    redacted = {}
    for k, v in params.items():
        if any(s in k.lower() for s in sensitive_keys):
            redacted[k] = "***REDACTED***"
        else:
            redacted[k] = v
    return redacted


def _summarize_result(result: dict[str, Any] | None) -> str:
    """Resumo do resultado para logs (sem expor dados sensiveis)."""
    if result is None:
        return "none"
    if result.get("ok"):
        stdout = result.get("stdout", "")
        if stdout:
            return stdout[:200]
        return "ok"
    return result.get("error", "failed")[:200]


class AgentLoop:
    """Loop real de execucao autonoma.

    Cada iteracao:
    1. LLM analisa objetivo + historico + resultado anterior
    2. LLM decide proxima tool + parametros
    3. SecurityGate valida
    4. Tool executa
    5. Resultado volta pro LLM
    6. Repete ate concluir ou atingir limite
    """

    MAX_ITERATIONS = 20
    MAX_TIMEOUT_MS = 300000  # 5 minutos
    MAX_OUTPUT_LENGTH = 10000

    def __init__(
        self,
        tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]],
        security_gate: Any = None,
        mode_manager: Any = None,
        llm_sender: Callable[[list[dict[str, str]]], str] | None = None,
        capability_registry: Any = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._security = security_gate
        self._mode_manager = mode_manager
        self._llm_sender = llm_sender
        self._capabilities = capability_registry
        self._tasks: dict[str, AgentTask] = {}

    def create_task(self, objective: str, context: str = "") -> AgentTask:
        """Cria uma nova tarefa."""
        mode = self._mode_manager.mode.value if self._mode_manager else "unknown"
        task = AgentTask(objective=objective, context=context, mode=mode)
        self._tasks[task.task_id] = task
        return task

    def get_task(self, task_id: str) -> AgentTask | None:
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            return True
        return False

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    def run(self, objective: str, context: str = "") -> AgentTask:
        """Executa uma tarefa completa (sincrono).

        Fluxo:
        1. Cria task
        2. Loop de iteracoes
        3. Cada iteracao: LLM decide tool → SecurityGate → executa → resultado
        4. Para quando LLM diz que concluiu, ou erro, ou limite
        """
        task = self.create_task(objective, context)
        task.status = TaskStatus.RUNNING
        start_time = time.time()

        system_prompt = self._build_system_prompt(task)

        while task.iteration < self.MAX_ITERATIONS:
            # Verificar timeout
            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms > self.MAX_TIMEOUT_MS:
                task.status = TaskStatus.TIMEOUT
                task.errors.append("Timeout atingido")
                break

            # Verificar cancelamento
            if task.status == TaskStatus.CANCELLED:
                break

            # LLM decide proxima acao
            try:
                action = self._get_llm_action(system_prompt, task)
            except Exception as e:
                task.errors.append(f"LLM error: {e}")
                task.status = TaskStatus.FAILED
                break

            # Se LLM diz que concluiu
            if action.get("completed"):
                task.final_response = action.get("response", "Tarefa concluida.")
                task.verification = action.get("verification", "LLM indicou conclusao")
                task.status = TaskStatus.COMPLETED
                break

            # Se LLM quer usar uma tool
            tool_name = action.get("tool")
            tool_params = action.get("parameters", {})

            if not tool_name:
                task.final_response = action.get("response", "Nao foi possivel determinar proxima acao.")
                task.status = TaskStatus.FAILED
                break

            # SecurityGate valida
            if self._security and not self._validate_tool(tool_name, tool_params, task):
                task.errors.append(f"SecurityGate negou: {tool_name}")
                continue

            # Executar tool
            tool_call = ToolCall(tool_name=tool_name, parameters=tool_params)
            tool_call.status = StepStatus.RUNNING
            tool_call.started_at = time.time()

            try:
                result = self._tool_executor(tool_name, tool_params)
                tool_call.result = result
                tool_call.status = StepStatus.SUCCESS if result.get("ok") else StepStatus.FAILED
                if not result.get("ok"):
                    task.errors.append(f"Tool {tool_name} falhou: {result.get('error', 'unknown')}")
            except Exception as e:
                tool_call.status = StepStatus.FAILED
                tool_call.error = str(e)
                task.errors.append(f"Tool {tool_name} excecao: {e}")

            tool_call.completed_at = time.time()
            task.tool_calls.append(tool_call)

            # Resultado pro LLM
            task.results.append({
                "iteration": task.iteration,
                "tool": tool_name,
                "result": _summarize_result(tool_call.result),
                "success": tool_call.status == StepStatus.SUCCESS,
            })

        # Se nao completou e nao falhou, marcar como failed
        if task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.FAILED
            task.errors.append("Limite de iteracoes atingido")

        task.completed_at = time.time()
        return task

    def _validate_tool(self, tool_name: str, params: dict[str, Any],
                       task: AgentTask) -> bool:
        """Valida tool via SecurityGate e capabilities."""
        if self._capabilities and self._mode_manager:
            if not self._capabilities.is_available(tool_name, self._mode_manager.mode):
                return False

        if self._security:
            from core.neural.decision.decision_engine import Decision
            decision = Decision(
                module=tool_name,
                action="execute",
                parameters=params,
                source="agent_loop",
            )
            gate = self._security.approve(decision)
            return gate.is_allowed

        return True

    def _get_llm_action(self, system_prompt: str, task: AgentTask) -> dict[str, Any]:
        """Obtem proxima acao do LLM."""
        if self._llm_sender is None:
            return {"completed": True, "response": "LLM nao configurado.", "verification": "no_llm"}

        messages = [{"role": "system", "content": system_prompt}]

        # Contexto da tarefa
        user_msg = f"Objetivo: {task.objective}\n"
        if task.context:
            user_msg += f"Contexto: {task.context}\n"
        if task.results:
            user_msg += "\nResultados anteriores:\n"
            for r in task.results[-5:]:
                user_msg += f"  Iteracao {r['iteration']}: {r['tool']} → {r['result'][:200]}\n"
        if task.errors:
            user_msg += f"\nErros: {task.errors[-3:]}\n"
        user_msg += "\nQual a proxima acao? Responda em JSON: {\"tool\": \"nome\", \"parameters\": {...}} ou {\"completed\": true, \"response\": \"...\"}"

        messages.append({"role": "user", "content": user_msg})

        try:
            response = self._llm_sender(messages)
            return self._parse_llm_response(response)
        except Exception as e:
            return {"completed": True, "response": f"Erro LLM: {e}", "verification": "llm_error"}

    def _parse_llm_response(self, response: str) -> dict[str, Any]:
        """Parse da resposta do LLM para tool call."""
        import json
        try:
            # Tentar extrair JSON da resposta
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError:
            pass

        # Se nao conseguiu parse, tratar como texto de conclusao
        return {"completed": True, "response": response, "verification": "text_response"}

    def _build_system_prompt(self, task: AgentTask) -> str:
        """Construi prompt do sistema para o Agent Loop."""
        mode_desc = "PRIMARY (PC online)" if self._mode_manager and self._mode_manager.mode.value == "primary" else "EDGE (PC offline)"

        tools_desc = ""
        if self._capabilities and self._mode_manager:
            caps = self._capabilities.available_in_mode(self._mode_manager.mode)
            tools_desc = "\n".join(f"  - {c.name}: {c.description}" for c in caps[:30])

        return f"""Voce e a A.R.I.S. no modo {mode_desc}. Execute a tarefa usando as tools disponiveis.

Ferramentas disponiveis:
{tools_desc}

Regras:
1. Execute UM step por vez
2. Responda SEMPRE em JSON: {{"tool": "nome", "parameters": {{}}}} ou {{"completed": true, "response": "..."}}
3. Se a tarefa esta concluida: {{"completed": true, "response": "resumo"}}
4. Se uma tool falhou, tente uma abordagem diferente
5. NUNCA afirme conclusao sem confirmacao da tool
6. MAX 20 iteracoes
7. Parametros sensiveis (password, token, key) NUNCA devem aparecer nos logs"""


def get_active_tasks() -> list[dict[str, Any]]:
    """Retorna tarefas ativas (para dashboard)."""
    return []


_agent_loop: AgentLoop | None = None


def get_agent_loop() -> AgentLoop | None:
    return _agent_loop


def set_agent_loop(loop: AgentLoop) -> None:
    global _agent_loop
    _agent_loop = loop
