"""Estado global do A.R.I.S. (Neural Core).

Representa o estado relevante do sistema em estruturas organizadas —
não uma variável global gigantesca. Um único objeto ``GlobalState``
agrega sub-estados coerentes que o Context Engine e os demais
componentes consultam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.neural.events import Event


@dataclass
class VoiceState:
    """Estado do subsistema de voz."""
    enabled: bool = True
    speaking: bool = False
    engine: str = "sapi"


@dataclass
class SchedulerState:
    """Estado do subsistema de agendamento."""
    running: bool = False
    pending_tasks: int = 0
    active_pomodoro: bool = False


@dataclass
class HardwareState:
    """Estado do subsistema de hardware (ESP32)."""
    connected: bool = False
    available: bool = True
    simulation: bool = False
    current_led_state: str = "unknown"


@dataclass
class PerceptionState:
    """Estado da camada de percepção (sensores + atenção atual)."""
    enabled: bool = False
    active_sensors: int = 0
    sensors: dict[str, str] = field(default_factory=dict)
    last_attention: str = "IGNORE"
    attention_score: float = 0.0
    attention_focus: str = ""


class GlobalState:
    """Estado global coerente do sistema.

    Registra eventos recentes, tarefa corrente, modo atual, processos
    ativos e os sub-estados de voz, agenda e hardware.
    """

    def __init__(self) -> None:
        self.current_task: str = ""
        self.current_goal: str = ""
        self.current_mode: str = "idle"
        self.last_event: Event | None = None
        self.active_processes: list[str] = []
        self.voice = VoiceState()
        self.scheduler = SchedulerState()
        self.hardware = HardwareState()
        self.perception = PerceptionState()
        self.event_history: list[Event] = []
        self.failure_history: list[str] = []
        self._history_maxlen = 50

    # ── Tarefa / modo ────────────────────────────────────────

    def set_current_task(self, task: str) -> None:
        """Define a tarefa atualmente em foco."""
        self.current_task = task

    def set_current_goal(self, goal: str) -> None:
        """Define o objetivo corrente (usado pelo Planner)."""
        self.current_goal = goal

    def set_mode(self, mode: str) -> None:
        """Define o modo de operação (idle, thinking, working...)."""
        self.current_mode = mode

    def set_goal(self, goal: str) -> None:
        """Alias curto para definir o objetivo corrente."""
        self.set_current_goal(goal)

    def clear_goal(self, reason: str = "") -> None:
        """Limpa o objetivo corrente (tarefa concluída/abortada)."""
        self.current_goal = ""

    def record_failure(self, message: str) -> None:
        """Registra uma falha recente no estado global."""
        self.failure_history.append(message)
        if len(self.failure_history) > self._history_maxlen:
            self.failure_history = self.failure_history[-self._history_maxlen:]

    # ── Eventos ──────────────────────────────────────────────

    def register_event(self, event: Event) -> None:
        """Registra o último evento e mantém o histórico recente."""
        self.last_event = event
        self.event_history.append(event)
        if len(self.event_history) > self._history_maxlen:
            self.event_history = self.event_history[-self._history_maxlen:]

    def recent_events(self, limit: int = 10) -> list[Event]:
        """Retorna os eventos mais recentes."""
        return list(self.event_history[-limit:])

    # ── Processos ativos ─────────────────────────────────────

    def process_started(self, name: str) -> None:
        """Marca o início de um processo ativo."""
        if name not in self.active_processes:
            self.active_processes.append(name)

    def process_finished(self, name: str) -> None:
        """Marca o fim de um processo ativo."""
        if name in self.active_processes:
            self.active_processes.remove(name)

    def update_voice(self, *, enabled: bool | None = None, speaking: bool | None = None) -> None:
        """Atualiza o sub-estado de voz."""
        if enabled is not None:
            self.voice.enabled = enabled
        if speaking is not None:
            self.voice.speaking = speaking

    def update_scheduler(self, *, running: bool | None = None, pending_tasks: int | None = None,
                         active_pomodoro: bool | None = None) -> None:
        """Atualiza o sub-estado de agendamento."""
        if running is not None:
            self.scheduler.running = running
        if pending_tasks is not None:
            self.scheduler.pending_tasks = pending_tasks
        if active_pomodoro is not None:
            self.scheduler.active_pomodoro = active_pomodoro

    def update_hardware(self, *, connected: bool | None = None, available: bool | None = None,
                        simulation: bool | None = None) -> None:
        """Atualiza o sub-estado de hardware."""
        if connected is not None:
            self.hardware.connected = connected
        if available is not None:
            self.hardware.available = available
        if simulation is not None:
            self.hardware.simulation = simulation

    def update_perception(self, *, enabled: bool | None = None, active_sensors: int | None = None,
                          sensors: dict[str, str] | None = None,
                          last_attention: str | None = None, attention_score: float | None = None,
                          attention_focus: str | None = None) -> None:
        """Atualiza o sub-estado de percepção."""
        if enabled is not None:
            self.perception.enabled = enabled
        if active_sensors is not None:
            self.perception.active_sensors = active_sensors
        if sensors is not None:
            self.perception.sensors = dict(sensors)
        if last_attention is not None:
            self.perception.last_attention = last_attention
        if attention_score is not None:
            self.perception.attention_score = attention_score
        if attention_focus is not None:
            self.perception.attention_focus = attention_focus

    # ── Snapshot ─────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Estado atual, pronto para contexto e relatórios."""
        return {
            "current_task": self.current_task,
            "current_goal": self.current_goal,
            "current_mode": self.current_mode,
            "active_processes": list(self.active_processes),
            "last_event": self.last_event.event_type if self.last_event else None,
            "voice": {
                "enabled": self.voice.enabled,
                "speaking": self.voice.speaking,
            },
            "scheduler": {
                "running": self.scheduler.running,
                "pending_tasks": self.scheduler.pending_tasks,
            },
            "hardware": {
                "connected": self.hardware.connected,
                "available": self.hardware.available,
                "simulation": self.hardware.simulation,
            },
            "perception": {
                "enabled": self.perception.enabled,
                "active_sensors": self.perception.active_sensors,
                "sensors": dict(self.perception.sensors),
                "last_attention": self.perception.last_attention,
                "attention_score": self.perception.attention_score,
                "attention_focus": self.perception.attention_focus,
            },
        }

    def describe(self) -> str:
        """Descrição textual curta para prompts."""
        snap = self.snapshot()
        parts = [f"Modo: {snap['current_mode']}"]
        if snap["current_task"]:
            parts.append(f"Tarefa: {snap['current_task']}")
        if snap["last_event"]:
            parts.append(f"Último evento: {snap['last_event']}")
        parts.append(
            f"Voz: {'on' if snap['voice']['enabled'] else 'off'} | "
            f"HW: {'conectado' if snap['hardware']['connected'] else 'offline'}"
        )
        parts.append(
            f"Percepção: {'on' if snap['perception']['enabled'] else 'off'} | "
            f"atenção: {snap['perception']['last_attention']}"
        )
        return " | ".join(parts)

    def __repr__(self) -> str:
        return f"GlobalState(mode={self.current_mode!r}, task={self.current_task!r})"
