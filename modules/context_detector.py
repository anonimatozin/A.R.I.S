"""Context Detector - Detecta a atividade atual do J.A.R.V.I.S.

Analisa o que o operador está fazendo e adapta respostas.
"""

import psutil
import time
from typing import Optional
from dataclasses import dataclass
from enum import Enum


class ActivityType(Enum):
    CODING = "coding"
    BROWSING = "browsing"
    GAMING = "gaming"
    WATCHING = "watching"
    WORKING = "working"
    IDLE = "idle"
    UNKNOWN = "unknown"


@dataclass
class ContextInfo:
    """Informações de contexto detectadas."""
    activity: ActivityType
    active_window: str
    active_process: str
    cpu_load: float
    memory_percent: float
    details: str


class ContextDetector:
    """Detector de contexto em tempo real."""

    def __init__(self):
        self._last_check = 0
        self._cache_duration = 2  # segundos
        self._cached_context: Optional[ContextInfo] = None

        # Processos conhecidos
        self._process_map = {
            "code": ActivityType.CODING,
            "devenv": ActivityType.CODING,
            "pycharm": ActivityType.CODING,
            "idea": ActivityType.CODING,
            "notepad++": ActivityType.CODING,
            "sublime": ActivityType.CODING,
            "atom": ActivityType.CODING,
            "cursor": ActivityType.CODING,
            "cursor.exe": ActivityType.CODING,
            "chrome": ActivityType.BROWSING,
            "firefox": ActivityType.BROWSING,
            "edge": ActivityType.BROWSING,
            "brave": ActivityType.BROWSING,
            "opera": ActivityType.BROWSING,
            "steam": ActivityType.GAMING,
            "epicgameslauncher": ActivityType.GAMING,
            "origin": ActivityType.GAMING,
            "battle.net": ActivityType.GAMING,
            "vlc": ActivityType.WATCHING,
            "mpc-hc": ActivityType.WATCHING,
            "potplayer": ActivityType.WATCHING,
            "netflix": ActivityType.WATCHING,
            "youtube": ActivityType.WATCHING,
            "word": ActivityType.WORKING,
            "excel": ActivityType.WORKING,
            "powerpoint": ActivityType.WORKING,
            "outlook": ActivityType.WORKING,
            "teams": ActivityType.WORKING,
            "slack": ActivityType.WORKING,
            "discord": ActivityType.WORKING,
        }

    def get_context(self) -> ContextInfo:
        """Detecta o contexto atual."""
        now = time.time()
        if self._cached_context and (now - self._last_check) < self._cache_duration:
            return self._cached_context

        active_window = self._get_active_window()
        active_process = self._get_active_process()
        cpu_load = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()

        activity = self._classify_activity(active_process, active_window)
        details = self._get_details(activity, active_window, active_process)

        context = ContextInfo(
            activity=activity,
            active_window=active_window,
            active_process=active_process,
            cpu_load=cpu_load,
            memory_percent=memory.percent,
            details=details,
        )

        self._cached_context = context
        self._last_check = now
        return context

    def _get_active_window(self) -> str:
        """Retorna o título da janela ativa."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        except Exception:
            return ""

    def _get_active_process(self) -> str:
        """Retorna o nome do processo ativo."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process = psutil.Process(pid.value)
            return process.name().lower().replace(".exe", "")
        except Exception:
            return ""

    def _classify_activity(self, process: str, window_title: str) -> ActivityType:
        """Classifica a atividade baseada no processo/janela."""
        # Verificar processo conhecido
        activity = self._process_map.get(process)
        if activity:
            return activity

        # Verificar título da janela
        title_lower = window_title.lower()
        for keyword, activity in self._process_map.items():
            if keyword in title_lower:
                return activity

        # Verificar se está ocioso (sem atividade de CPU)
        if psutil.cpu_percent(interval=0.1) < 5:
            return ActivityType.IDLE

        return ActivityType.UNKNOWN

    def _get_details(self, activity: ActivityType, window: str, process: str) -> str:
        """Gera detalhes da atividade."""
        if activity == ActivityType.CODING:
            return f"Programando em {process}"
        elif activity == ActivityType.BROWSING:
            return f"Navegando: {window[:60]}"
        elif activity == ActivityType.GAMING:
            return f"Jogando: {process}"
        elif activity == ActivityType.WATCHING:
            return f"Assistindo: {window[:60]}"
        elif activity == ActivityType.WORKING:
            return f"Trabalhando em {process}"
        elif activity == ActivityType.IDLE:
            return "Sistema ocioso"
        return f"Atividade: {process}"

    def get_productivity_score(self) -> float:
        """Calcula um score de produtividade (0.0 a 1.0)."""
        context = self.get_context()
        scores = {
            ActivityType.CODING: 0.9,
            ActivityType.WORKING: 0.8,
            ActivityType.BROWSING: 0.5,
            ActivityType.WATCHING: 0.3,
            ActivityType.GAMING: 0.2,
            ActivityType.IDLE: 0.0,
            ActivityType.UNKNOWN: 0.4,
        }
        base_score = scores.get(context.activity, 0.4)

        # Ajustar por carga do sistema
        if context.cpu_load > 80:
            base_score *= 0.8

        return min(1.0, max(0.0, base_score))

    def should_suggest_break(self, work_minutes: int) -> bool:
        """Sugere uma pausa se trabalhou muito tempo."""
        return work_minutes >= 45

    def format_context(self) -> str:
        """Formata o contexto para exibição."""
        ctx = self.get_context()
        activity_names = {
            ActivityType.CODING: "💻 Programando",
            ActivityType.BROWSING: "🌐 Navegando",
            ActivityType.GAMING: "🎮 Jogando",
            ActivityType.WATCHING: "📺 Assistindo",
            ActivityType.WORKING: "💼 Trabalhando",
            ActivityType.IDLE: "😴 Ocioso",
            ActivityType.UNKNOWN: "❓ Desconhecido",
        }
        activity = activity_names.get(ctx.activity, "❓ Desconhecido")
        score = self.get_productivity_score()

        return (
            f"Atividade: {activity}\n"
            f"Janela: {ctx.active_window[:60]}\n"
            f"CPU: {ctx.cpu_load:.1f}% | RAM: {ctx.memory_percent:.1f}%\n"
            f"Produtividade: {score:.0%}"
        )
