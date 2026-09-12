"""Safety Tiers - Sistema de Segurança do A.R.I.S.

Define níveis de permissão para ações perigosas.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class SafetyLevel(Enum):
    SAFE = 1       # Ações inofensivas (ler, pesquisar, info)
    CAUTION = 2    # Ações moderadas (abrir apps, digitar)
    DANGER = 3     # Ações arriscadas (fechar processos, deletar)
    CRITICAL = 4   # Ações críticas (desligar, formatar, sudo)


@dataclass
class SafetyAction:
    """Uma ação com nível de segurança."""
    name: str
    level: SafetyLevel
    requires_confirmation: bool = False
    requires_password: bool = False
    description: str = ""


class SafetyManager:
    """Gerenciador de segurança com níveis de permissão."""

    # Mapeamento de ações por nível
    SAFE_ACTIONS = [
        "weather", "websearch", "sys", "search",
        "remember", "config", "speak", "context",
        "clipboard_get", "mouse_position", "get_screen_size",
        "list_windows", "list_tasks", "pomodoro_status",
    ]

    CAUTION_ACTIONS = [
        "open_app", "type_text", "hotkey", "press_key",
        "volume_up", "volume_down", "volume_mute",
        "media_play_pause", "media_next", "media_previous",
        "mouse_move", "mouse_click", "mouse_scroll",
        "clipboard_set", "notify", "screenshot",
    ]

    DANGER_ACTIONS = [
        "close_app", "focus_window", "minimize_all",
        "cancel_task", "delete_memory",
    ]

    CRITICAL_ACTIONS = [
        "shutdown", "restart", "logoff",
        "format_disk", "delete_system",
    ]

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir
        self._password_hash: str | None = None
        self._audit_log: list[dict] = []
        self._audit_file = data_dir / "safety_audit.json" if data_dir else None
        self._master_password: str | None = None

        self._action_map: dict[str, SafetyAction] = {}
        self._init_action_map()

        if self._audit_file:
            self._load_audit()

    def _init_action_map(self) -> None:
        """Inicializa o mapa de ações."""
        for action in self.SAFE_ACTIONS:
            self._action_map[action] = SafetyAction(
                name=action, level=SafetyLevel.SAFE
            )
        for action in self.CAUTION_ACTIONS:
            self._action_map[action] = SafetyAction(
                name=action, level=SafetyLevel.CAUTION, requires_confirmation=False
            )
        for action in self.DANGER_ACTIONS:
            self._action_map[action] = SafetyAction(
                name=action, level=SafetyLevel.DANGER, requires_confirmation=True
            )
        for action in self.CRITICAL_ACTIONS:
            self._action_map[action] = SafetyAction(
                name=action, level=SafetyLevel.CRITICAL,
                requires_confirmation=True, requires_password=True
            )

    def set_master_password(self, password: str) -> str:
        """Define a senha mestra."""
        self._password_hash = hashlib.sha256(password.encode()).hexdigest()
        self._master_password = password
        return "Senha mestra definida"

    def check_password(self, password: str) -> bool:
        """Verifica a senha mestra."""
        if not self._password_hash:
            return True  # Sem senha definida, permite tudo
        return hashlib.sha256(password.encode()).hexdigest() == self._password_hash

    def get_action_level(self, action: str) -> SafetyLevel:
        """Retorna o nível de segurança de uma ação."""
        safety_action = self._action_map.get(action)
        if safety_action:
            return safety_action.level
        return SafetyLevel.CAUTION  # Default: cautela

    def can_execute(self, action: str, password: str | None = None) -> tuple[bool, str]:
        """Verifica se uma ação pode ser executada.

        Returns:
            Tupla (pode_executar, mensagem).
        """
        level = self.get_action_level(action)

        if level == SafetyLevel.SAFE:
            return True, "Ação segura"

        if level == SafetyLevel.CAUTION:
            return True, "Ação moderada"

        if level == SafetyLevel.DANGER:
            self._log_audit(action, "danger_confirmed")
            return True, "Ação arriscada confirmada"

        if level == SafetyLevel.CRITICAL:
            if password and self.check_password(password):
                self._log_audit(action, "critical_approved")
                return True, "Ação crítica aprovada"
            return False, "Senha mestra necessária para esta ação"

        return False, "Nível de segurança desconhecido"

    def _log_audit(self, action: str, result: str) -> None:
        """Registra no audit log."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "result": result,
        }
        self._audit_log.append(entry)
        self._save_audit()

    def _load_audit(self) -> None:
        """Carrega audit log."""
        if self._audit_file and self._audit_file.exists():
            try:
                self._audit_log = json.loads(self._audit_file.read_text(encoding="utf-8"))
            except Exception:
                self._audit_log = []

    def _save_audit(self) -> None:
        """Salva audit log."""
        if self._audit_file:
            try:
                self._audit_file.write_text(
                    json.dumps(self._audit_log[-500:], indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

    def get_audit_log(self, limit: int = 20) -> list[dict]:
        """Retorna últimas entradas do audit log."""
        return self._audit_log[-limit:]

    def get_safety_report(self) -> str:
        """Gera relatório de segurança."""
        levels = {"SAFE": 0, "CAUTION": 0, "DANGER": 0, "CRITICAL": 0}
        for action in self._action_map.values():
            levels[action.level.name] += 1

        return (
            f"Segurança: {len(self._action_map)} ações mapeadas\n"
            f"  🟢 SAFE: {levels['SAFE']}\n"
            f"  🟡 CAUTION: {levels['CAUTION']}\n"
            f"  🟠 DANGER: {levels['DANGER']}\n"
            f"  🔴 CRITICAL: {levels['CRITICAL']}\n"
            f"  Audit log: {len(self._audit_log)} entradas"
        )
