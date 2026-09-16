"""Instance Manager — garante instancia unica do A.R.I.S. Local Agent.

Usa arquivo de lock + PID para evitar duplicacao.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LOCK_FILE = Path.home() / ".aris" / "agent.lock"
PID_FILE = Path.home() / ".aris" / "agent.pid"
SOCKET_NAME = "\\\\.\\pipe\\aris_agent"


class InstanceManager:
    """Gerencia instancia unica do A.R.I.S. Agent."""

    def __init__(self) -> None:
        self._lock_path = LOCK_FILE
        self._pid_path = PID_FILE
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

    def is_running(self) -> bool:
        """Verifica se ja existe uma instancia rodando."""
        if not self._pid_path.exists():
            return False
        try:
            pid = int(self._pid_path.read_text().strip())
            return self._is_process_alive(pid)
        except (ValueError, OSError):
            return False

    def get_running_pid(self) -> int | None:
        """Retorna o PID da instancia em execucao."""
        if not self._pid_path.exists():
            return None
        try:
            pid = int(self._pid_path.read_text().strip())
            if self._is_process_alive(pid):
                return pid
        except (ValueError, OSError):
            pass
        return None

    def acquire(self) -> bool:
        """Tenta adquirir lock de instancia unica.

        Returns:
            True se conseguiu (somos a unica instancia).
        """
        if self.is_running():
            return False
        try:
            self._pid_path.write_text(str(os.getpid()))
            return True
        except OSError:
            return False

    def release(self) -> None:
        """Libera o lock."""
        try:
            if self._pid_path.exists():
                pid = int(self._pid_path.read_text().strip())
                if pid == os.getpid():
                    self._pid_path.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass

    def force_release(self) -> bool:
        """Forca liberacao (mata processo antigo)."""
        pid = self.get_running_pid()
        if pid is None:
            self._pid_path.unlink(missing_ok=True)
            return True
        try:
            import signal
            os.kill(pid, signal.SIGTERM)
            import time
            time.sleep(1)
            if not self._is_process_alive(pid):
                self._pid_path.unlink(missing_ok=True)
                return True
        except (OSError, ProcessLookupError):
            self._pid_path.unlink(missing_ok=True)
            return True
        return False

    def _is_process_alive(self, pid: int) -> bool:
        """Verifica se processo esta ativo."""
        try:
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except (OSError, AttributeError):
            return False
