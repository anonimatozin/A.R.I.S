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
        "gmail_search", "gmail_read", "gmail_list",
        "gmail_mark_read", "gmail_mark_unread",
    ]

    CAUTION_ACTIONS = [
        "open_app", "type_text", "hotkey", "press_key",
        "volume_up", "volume_down", "volume_mute",
        "media_play_pause", "media_next", "media_previous",
        "mouse_move", "mouse_click", "mouse_scroll",
        "clipboard_set", "notify", "screenshot",
        "gmail_untrash",
    ]

    DANGER_ACTIONS = [
        "close_app", "focus_window", "minimize_all",
        "cancel_task", "delete_memory",
        "gmail_trash",
    ]

    CRITICAL_ACTIONS = [
        "shutdown", "restart", "logoff",
        "format_disk", "delete_system",
    ]

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir
        self._password_hash: str | None = None
        self._password_salt: str = ""
        self._audit_log: list[dict] = []
        self._audit_file = data_dir / "safety_audit.json" if data_dir else None
        self._master_password: str | None = None
        self._secrets_file = data_dir / "secrets.enc" if data_dir else None
        self._key_file = data_dir / ".secret_key" if data_dir else None
        self._fernet = self._init_fernet()

        self._action_map: dict[str, SafetyAction] = {}
        self._init_action_map()

        if self._audit_file:
            self._load_audit()

    def _init_fernet(self):
        """Inicializa Fernet encryption com key persistente."""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            return None
        if not self._key_file:
            return None
        if self._key_file.exists():
            key = self._key_file.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            self._key_file.parent.mkdir(parents=True, exist_ok=True)
            self._key_file.write_bytes(key)
        return Fernet(key)

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
        """Define a senha mestra com pbkdf2 (NÃO aceita vazia)."""
        if not password or len(password) < 4:
            return "Senha muito curta (mínimo 4 caracteres)"
        import os
        salt = os.urandom(16)
        self._password_salt = salt.hex()
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=100_000)
        self._password_hash = dk.hex()
        self._master_password = password
        return "Senha mestra definida"

    def check_password(self, password: str) -> bool:
        """Verifica a senha mestra (pbkdf2, com fallback SHA-256 legado + rehash).

        Se o hash legado SHA-256 é verificado com sucesso, re-hash
        imediatamente com pbkdf2 e atualiza o registro.
        """
        if not self._password_hash:
            return True  # Sem senha definida, permite tudo
        if not password:
            return False  # Nunca aceitar vazio quando hash existe

        # Tentar pbkdf2 primeiro (novo formato)
        if self._password_salt:
            import os
            salt = bytes.fromhex(self._password_salt)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=100_000)
            if dk.hex() == self._password_hash:
                return True

        # Fallback: verificar contra hash SHA-256 legado (sem sal)
        legacy = hashlib.sha256(password.encode()).hexdigest()
        if legacy == self._password_hash:
            # Re-hash imediatamente com pbkdf2 e atualiza o registro
            self._upgrade_password_hash(password)
            return True

        return False

    def _upgrade_password_hash(self, password: str) -> None:
        """Migra hash legado SHA-256 para pbkdf2 (chamado no login bem-sucedido)."""
        import os
        salt = os.urandom(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=100_000)
        self._password_salt = salt.hex()
        self._password_hash = dk.hex()
        # Log (sem expor a senha)
        if self._audit_file:
            self._log_audit("password_upgraded", "credential_migrated_to_pbkdf2")

    # ── Secret Storage (Fernet encrypted) ──────────────────

    def store_secret(self, key: str, value: str) -> bool:
        """Armazena um secret criptografado (Fernet) em disco.

        Args:
            key: Identificador do secret (ex: "gmail:user@gmail.com:token").
            value: Valor a ser criptografado.

        Returns:
            True se armazenado com sucesso.
        """
        if self._fernet is None or not self._secrets_file:
            return False
        secrets = self._load_secrets_raw()
        encrypted = self._fernet.encrypt(value.encode()).decode()
        secrets[key] = encrypted
        return self._save_secrets_raw(secrets)

    def load_secret(self, key: str) -> str | None:
        """Carrega e descriptografa um secret.

        Returns:
            Valor descriptografado ou None se não encontrado.
        """
        if self._fernet is None or not self._secrets_file:
            return None
        secrets = self._load_secrets_raw()
        encrypted = secrets.get(key)
        if encrypted is None:
            return None
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except Exception:
            return None

    def delete_secret(self, key: str) -> bool:
        """Remove um secret do armazenamento."""
        if self._fernet is None or not self._secrets_file:
            return False
        secrets = self._load_secrets_raw()
        if key in secrets:
            del secrets[key]
            return self._save_secrets_raw(secrets)
        return False

    def _load_secrets_raw(self) -> dict[str, str]:
        """Carrega secrets criptografados do disco."""
        if not self._secrets_file or not self._secrets_file.exists():
            return {}
        try:
            import json
            return json.loads(self._secrets_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_secrets_raw(self, secrets: dict[str, str]) -> bool:
        """Salva secrets criptografados no disco."""
        if not self._secrets_file:
            return False
        try:
            import json
            self._secrets_file.parent.mkdir(parents=True, exist_ok=True)
            self._secrets_file.write_text(
                json.dumps(secrets, indent=2), encoding="utf-8"
            )
            return True
        except Exception:
            return False

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
