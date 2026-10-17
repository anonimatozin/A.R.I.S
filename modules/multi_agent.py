"""Multi-Agent - Delegação de Tarefas do A.R.I.S.

Sistema de agentes especializados com delegação.
Inspirado em OpenClaw e vierisid/aris.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class AgentStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentTask:
    """Uma tarefa delegada a um agente."""
    id: str
    description: str
    agent_type: str
    status: AgentStatus = AgentStatus.IDLE
    result: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str | None = None
    timeout: int = 60  # segundos


@dataclass
class Agent:
    """Um agente especializado."""
    id: str
    name: str
    agent_type: str
    capabilities: list[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    tasks_completed: int = 0
    current_task: str | None = None


class MultiAgentSystem:
    """Sistema multi-agente para delegação de tarefas."""

    # Agentes pré-definidos
    DEFAULT_AGENTS = [
        {
            "name": "Research Agent",
            "type": "research",
            "capabilities": ["web_search", "summarize", "fact_check", "analyze"],
        },
        {
            "name": "Code Agent",
            "type": "code",
            "capabilities": ["write_code", "review_code", "debug", "refactor"],
        },
        {
            "name": "File Agent",
            "type": "files",
            "capabilities": ["read_file", "write_file", "organize", "backup"],
        },
        {
            "name": "System Agent",
            "type": "system",
            "capabilities": ["monitor", "diagnose", "optimize", "cleanup"],
        },
        {
            "name": "Communication Agent",
            "type": "communication",
            "capabilities": ["email", "notify", "schedule", "message"],
        },
    ]

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir
        self._agents: dict[str, Agent] = {}
        self._tasks: dict[str, AgentTask] = {}
        self._task_queue: list[str] = []
        self._handlers: dict[str, Callable] = {}
        self._counter = 0

        self._init_default_agents()

    def _init_default_agents(self) -> None:
        """Inicializa agentes padrão."""
        for agent_def in self.DEFAULT_AGENTS:
            agent = Agent(
                id=self._next_id("agent"),
                name=agent_def["name"],
                agent_type=agent_def["type"],
                capabilities=agent_def["capabilities"],
            )
            self._agents[agent.id] = agent

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    # ── Agentes ────────────────────────────────────────────

    def register_agent(
        self,
        name: str,
        agent_type: str,
        capabilities: list[str],
    ) -> Agent:
        """Registra um novo agente."""
        agent = Agent(
            id=self._next_id("agent"),
            name=name,
            agent_type=agent_type,
            capabilities=capabilities,
        )
        self._agents[agent.id] = agent
        return agent

    def get_agent(self, agent_type: str) -> Agent | None:
        """Busca um agente por tipo."""
        for agent in self._agents.values():
            if agent.agent_type == agent_type and agent.status != AgentStatus.WORKING:
                return agent
        return None

    def get_best_agent(self, capability: str) -> Agent | None:
        """Busca o melhor agente para uma capacidade."""
        candidates = [
            a for a in self._agents.values()
            if capability in a.capabilities and a.status != AgentStatus.WORKING
        ]
        if candidates:
            # Ordenar por menos tarefas completadas (balanceamento)
            return min(candidates, key=lambda a: a.tasks_completed)
        return None

    def list_agents(self) -> list[dict]:
        """Lista todos os agentes."""
        return [
            {
                "id": a.id,
                "name": a.name,
                "type": a.agent_type,
                "status": a.status.value,
                "capabilities": a.capabilities,
                "tasks_completed": a.tasks_completed,
            }
            for a in self._agents.values()
        ]

    # ── Tarefas ────────────────────────────────────────────

    def delegate_task(
        self,
        description: str,
        agent_type: str | None = None,
        capability: str | None = None,
        timeout: int = 60,
    ) -> AgentTask | None:
        """Delega uma tarefa a um agente.

        Args:
            description: Descrição da tarefa.
            agent_type: Tipo do agente (opcional).
            capability: Capacidade necessária (opcional).
            timeout: Timeout em segundos.

        Returns:
            Task criada ou None.
        """
        # Encontrar agente adequado
        agent = None
        if agent_type:
            agent = self.get_agent(agent_type)
        elif capability:
            agent = self.get_best_agent(capability)
        else:
            # Encontrar qualquer agente livre
            for a in self._agents.values():
                if a.status != AgentStatus.WORKING:
                    agent = a
                    break

        if not agent:
            return None

        task = AgentTask(
            id=self._next_id("task"),
            description=description,
            agent_type=agent.agent_type,
            timeout=timeout,
        )

        self._tasks[task.id] = task
        agent.status = AgentStatus.WORKING
        agent.current_task = task.id
        task.status = AgentStatus.WORKING

        return task

    def complete_task(self, task_id: str, result: str) -> bool:
        """Marca uma tarefa como concluída."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.status = AgentStatus.COMPLETED
        task.result = result
        task.completed_at = datetime.now().isoformat()

        # Atualizar agente
        for agent in self._agents.values():
            if agent.current_task == task_id:
                agent.status = AgentStatus.IDLE
                agent.current_task = None
                agent.tasks_completed += 1
                break

        return True

    def fail_task(self, task_id: str, error: str) -> bool:
        """Marca uma tarefa como falhou."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.status = AgentStatus.FAILED
        task.error = error
        task.completed_at = datetime.now().isoformat()

        for agent in self._agents.values():
            if agent.current_task == task_id:
                agent.status = AgentStatus.IDLE
                agent.current_task = None
                break

        return True

    def get_task(self, task_id: str) -> AgentTask | None:
        """Retorna uma tarefa."""
        return self._tasks.get(task_id)

    def list_tasks(self, status: AgentStatus | None = None) -> list[dict]:
        """Lista tarefas."""
        tasks = self._tasks.values()
        if status:
            tasks = [t for t in tasks if t.status == status]
        return [asdict(t) for t in tasks]

    # ── Handlers ───────────────────────────────────────────

    def register_handler(self, capability: str, handler: Callable) -> None:
        """Registra um handler para uma capacidade."""
        self._handlers[capability] = handler

    def execute_task(self, task_id: str) -> str:
        """Executa uma tarefa usando o handler registrado."""
        task = self._tasks.get(task_id)
        if not task:
            return "Tarefa não encontrada"

        # Enhandler baseado na descrição
        handler = self._handlers.get("default")
        for cap, h in self._handlers.items():
            if cap in task.description.lower():
                handler = h
                break

        if not handler:
            return "Nenhum handler registrado"

        try:
            result = handler(task.description)
            self.complete_task(task_id, result)
            return result
        except Exception as e:
            self.fail_task(task_id, str(e))
            return f"Erro: {e}"

    # ── Orquestração ───────────────────────────────────────

    def decompose_task(self, task_description: str) -> list[str]:
        """Decompõe uma tarefa complexa em subtarefas.

        Usa heurísticas simples.
        """
        subtasks = []

        keywords = {
            "pesquisar": ["research", "web_search"],
            "analisar": ["analyze", "summarize"],
            "criar": ["write_code", "create"],
            "organizar": ["organize", "files"],
            "monitorar": ["monitor", "system"],
            "enviar": ["email", "notify"],
        }

        desc_lower = task_description.lower()
        for keyword, caps in keywords.items():
            if keyword in desc_lower:
                subtasks.append(f"{keyword} {task_description}")

        if not subtasks:
            subtasks.append(task_description)

        return subtasks

    def get_status(self) -> dict:
        """Retorna status do sistema."""
        return {
            "agents": len(self._agents),
            "tasks_total": len(self._tasks),
            "tasks_pending": len([t for t in self._tasks.values() if t.status == AgentStatus.IDLE]),
            "tasks_working": len([t for t in self._tasks.values() if t.status == AgentStatus.WORKING]),
            "tasks_completed": len([t for t in self._tasks.values() if t.status == AgentStatus.COMPLETED]),
            "tasks_failed": len([t for t in self._tasks.values() if t.status == AgentStatus.FAILED]),
        }

    def format_status(self) -> str:
        """Formata status do sistema."""
        status = self.get_status()
        lines = [
            "🤖 Multi-Agent System",
            f"   Agentes: {status['agents']}",
            f"   Tarefas: {status['tasks_total']} total",
            f"     Pendentes: {status['tasks_pending']}",
            f"     Executando: {status['tasks_working']}",
            f"     Concluídas: {status['tasks_completed']}",
            f"     Falhas: {status['tasks_failed']}",
        ]

        # Status de cada agente
        for agent in self._agents.values():
            status_icon = "🟢" if agent.status == AgentStatus.IDLE else "🟡" if agent.status == AgentStatus.WORKING else "⚪"
            lines.append(f"   {status_icon} {agent.name} ({agent.agent_type}) — {agent.tasks_completed} tarefas")

        return "\n".join(lines)
