"""Notificações Windows do J.A.R.V.I.S.

Sistema de notificações nativas do Windows.
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional
from datetime import datetime


class NotificationManager:
    """Gerenciador de notificações do Windows."""

    def __init__(self, data_dir: Optional[Path] = None):
        self._data_dir = data_dir
        self._history_file = data_dir / "notifications.json" if data_dir else None
        self._history: list[dict] = []
        self._available = False

        self._init_system()
        if self._history_file:
            self._load_history()

    def _init_system(self) -> None:
        """Inicializa o sistema de notificações."""
        if sys.platform == "win32":
            self._available = True

    def _load_history(self) -> None:
        """Carrega histórico de notificações."""
        if self._history_file and self._history_file.exists():
            try:
                self._history = json.loads(self._history_file.read_text(encoding="utf-8"))
            except Exception:
                self._history = []

    def _save_history(self) -> None:
        """Salva histórico."""
        if self._history_file:
            try:
                self._history_file.write_text(
                    json.dumps(self._history[-100:], indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

    def notify(
        self,
        title: str,
        message: str,
        duration: int = 5,
        icon: Optional[str] = None,
    ) -> str:
        """Envia uma notificação nativa do Windows.

        Args:
            title: Título da notificação.
            message: Corpo da notificação.
            duration: Duração em segundos.
            icon: Caminho para ícone (opcional).

        Returns:
            Mensagem de resultado.
        """
        # Registrar no histórico
        entry = {
            "title": title,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }
        self._history.append(entry)
        self._save_history()

        if not self._available:
            return f"Notificação registrada: {title}"

        # Tentar win10toast
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(
                title,
                message,
                duration=duration,
                threaded=True,
                icon_path=icon,
            )
            return f"Notificação enviada: {title}"
        except ImportError:
            pass

        # Tentar plyer
        try:
            from plyer import notification
            notification.notify(
                title=title,
                message=message,
                timeout=duration,
            )
            return f"Notificação enviada: {title}"
        except ImportError:
            pass

        # Fallback: PowerShell balloon
        try:
            ps_script = f'''
            [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
            $balloon = New-Object System.Windows.Forms.NotifyIcon
            $balloon.Icon = [System.Drawing.SystemIcons]::Information
            $balloon.BalloonTipIcon = "Info"
            $balloon.BalloonTipTitle = "{title}"
            $balloon.BalloonTipText = "{message}"
            $balloon.Visible = $true
            $balloon.ShowBalloonTip({duration * 1000})
            Start-Sleep -Seconds {duration}
            $balloon.Dispose()
            '''
            import subprocess
            subprocess.run(["powershell", "-Command", ps_script], capture_output=True, timeout=duration + 5)
            return f"Notificação enviada: {title}"
        except Exception:
            return f"Notificação registrada (sem exibição): {title}"

    def get_history(self, limit: int = 10) -> list[dict]:
        """Retorna histórico de notificações."""
        return self._history[-limit:]

    def clear_history(self) -> str:
        """Limpa histórico."""
        self._history = []
        self._save_history()
        return "Histórico de notificações limpo"
