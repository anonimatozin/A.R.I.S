"""Scheduler - Agendamentos e Lembretes do J.A.R.V.I.S.

Gerencia lembretes, tarefas agendadas e pomodoro.
"""

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum


class TaskPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    MISSED = "missed"


@dataclass
class ScheduledTask:
    """Uma tarefa agendada."""
    id: str
    title: str
    description: str
    scheduled_time: str  # ISO format
    task_type: str  # "reminder", "recurring", "pomodoro"
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    recurring_interval: Optional[int] = None  # minutos
    callback_data: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class PomodoroTimer:
    """Timer Pomodoro."""

    def __init__(
        self,
        work_minutes: int = 25,
        short_break: int = 5,
        long_break: int = 15,
    ):
        self.work_minutes = work_minutes
        self.short_break = short_break
        self.long_break = long_break
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._on_tick: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None
        self._current_session = 0
        self._total_sessions = 4

    def start(self, on_tick: Optional[Callable] = None, on_complete: Optional[Callable] = None) -> str:
        """Inicia um pomodoro."""
        if self._running:
            return "Pomodoro já em andamento"

        self._on_tick = on_tick
        self._on_complete = on_complete
        self._running = True
        self._paused = False
        self._current_session = 0

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return f"Pomodoro iniciado: {self.work_minutes}min trabalho"

    def pause(self) -> str:
        """Pausa o pomodoro."""
        if self._running:
            self._paused = not self._paused
            return "Pomodoro pausado" if self._paused else "Pomodoro retomado"
        return "Nenhum pomodoro em andamento"

    def stop(self) -> str:
        """Para o pomodoro."""
        self._running = False
        self._paused = False
        return "Pomodoro finalizado"

    def _run(self) -> None:
        """Loop do pomodoro."""
        while self._running and self._current_session < self._total_sessions:
            # Fase de trabalho
            remaining = self.work_minutes * 60
            while remaining > 0 and self._running:
                if not self._paused:
                    if self._on_tick:
                        self._on_tick(remaining, "work")
                    time.sleep(1)
                    remaining -= 1
                else:
                    time.sleep(0.5)

            if not self._running:
                break

            self._current_session += 1

            if self._on_complete:
                self._on_complete(f"Sessão {self._current_session}/{self._total_sessions} concluída")

            # Pausa
            break_time = self.long_break if self._current_session % 4 == 0 else self.short_break
            remaining = break_time * 60
            while remaining > 0 and self._running:
                if not self._paused:
                    if self._on_tick:
                        self._on_tick(remaining, "break")
                    time.sleep(1)
                    remaining -= 1
                else:
                    time.sleep(0.5)

        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "paused": self._paused,
            "session": self._current_session,
            "total_sessions": self._total_sessions,
        }


class Scheduler:
    """Gerenciador de agendamentos."""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._tasks_file = data_dir / "scheduled_tasks.json"
        self._tasks: list[ScheduledTask] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: dict[str, Callable] = {}
        self._pomodoro = PomodoroTimer()

        self._load_tasks()

    def _load_tasks(self) -> None:
        """Carrega tarefas do disco."""
        if self._tasks_file.exists():
            try:
                data = json.loads(self._tasks_file.read_text(encoding="utf-8"))
                for item in data:
                    item["priority"] = TaskPriority(item.get("priority", 2))
                    item["status"] = TaskStatus(item.get("status", "pending"))
                    self._tasks.append(ScheduledTask(**item))
            except Exception:
                self._tasks = []

    def _save_tasks(self) -> None:
        """Salva tarefas no disco."""
        data = []
        for task in self._tasks:
            d = asdict(task)
            d["priority"] = task.priority.value
            d["status"] = task.status.value
            data.append(d)
        self._tasks_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_reminder(
        self,
        title: str,
        when: datetime,
        description: str = "",
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> ScheduledTask:
        """Adiciona um lembrete."""
        task = ScheduledTask(
            id=f"rem_{int(time.time()*1000)}",
            title=title,
            description=description,
            scheduled_time=when.isoformat(),
            task_type="reminder",
            priority=priority,
        )
        self._tasks.append(task)
        self._save_tasks()
        return task

    def add_recurring(
        self,
        title: str,
        interval_minutes: int,
        description: str = "",
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> ScheduledTask:
        """Adiciona uma tarefa recorrente."""
        next_time = datetime.now() + timedelta(minutes=interval_minutes)
        task = ScheduledTask(
            id=f"rec_{int(time.time()*1000)}",
            title=title,
            description=description,
            scheduled_time=next_time.isoformat(),
            task_type="recurring",
            priority=priority,
            recurring_interval=interval_minutes,
        )
        self._tasks.append(task)
        self._save_tasks()
        return task

    def cancel_task(self, task_id: str) -> str:
        """Cancela uma tarefa."""
        for task in self._tasks:
            if task.id == task_id:
                task.status = TaskStatus.CANCELLED
                self._save_tasks()
                return f"Tarefa '{task.title}' cancelada"
        return "Tarefa não encontrada"

    def list_tasks(self, include_completed: bool = False) -> list[ScheduledTask]:
        """Lista tarefas."""
        if include_completed:
            return list(self._tasks)
        return [t for t in self._tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]

    def get_pending_count(self) -> int:
        """Retorna número de tarefas pendentes."""
        return len([t for t in self._tasks if t.status == TaskStatus.PENDING])

    def start_checker(self, callback: Optional[Callable] = None) -> None:
        """Inicia o verificador de tarefas em background."""
        self._running = True
        self._thread = threading.Thread(target=self._check_loop, args=(callback,), daemon=True)
        self._thread.start()

    def stop_checker(self) -> None:
        """Para o verificador."""
        self._running = False

    def _check_loop(self, callback: Optional[Callable] = None) -> None:
        """Loop de verificação de tarefas."""
        while self._running:
            now = datetime.now()
            for task in self._tasks:
                if task.status != TaskStatus.PENDING:
                    continue

                try:
                    scheduled = datetime.fromisoformat(task.scheduled_time)
                except ValueError:
                    continue

                if now >= scheduled:
                    task.status = TaskStatus.COMPLETED
                    if callback:
                        callback(task)

                    # Recorrente: reagendar
                    if task.task_type == "recurring" and task.recurring_interval:
                        task.scheduled_time = (now + timedelta(minutes=task.recurring_interval)).isoformat()
                        task.status = TaskStatus.PENDING

            self._save_tasks()
            time.sleep(10)

    # ── Pomodoro ───────────────────────────────────────────

    def start_pomodoro(self, work_minutes: int = 25) -> str:
        """Inicia um pomodoro."""
        self._pomodoro.work_minutes = work_minutes
        return self._pomodoro.start(
            on_complete=lambda msg: print(f"\n  [POMODORO] {msg}")
        )

    def pause_pomodoro(self) -> str:
        return self._pomodoro.pause()

    def stop_pomodoro(self) -> str:
        return self._pomodoro.stop()

    def pomodoro_status(self) -> dict:
        return self._pomodoro.status

    def format_task_list(self, tasks: list[ScheduledTask]) -> str:
        """Formata lista de tarefas para exibição."""
        if not tasks:
            return "Nenhuma tarefa agendada."

        lines = []
        priority_icons = {
            TaskPriority.LOW: "🟢",
            TaskPriority.MEDIUM: "🟡",
            TaskPriority.HIGH: "🟠",
            TaskPriority.URGENT: "🔴",
        }
        status_icons = {
            TaskStatus.PENDING: "⏳",
            TaskStatus.RUNNING: "▶️",
            TaskStatus.COMPLETED: "✅",
            TaskStatus.CANCELLED: "❌",
            TaskStatus.MISSED: "⚠️",
        }

        for task in tasks:
            icon = priority_icons.get(task.priority, "⚪")
            status = status_icons.get(task.status, "❓")
            when = task.scheduled_time[:16].replace("T", " ")
            lines.append(f"  {icon} {status} [{task.id}] {task.title} — {when}")

        return "\n".join(lines)
