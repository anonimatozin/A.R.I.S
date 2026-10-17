"""PC Control — shutdown, restart, lock, sleep do PC.

pc_shutdown/restart sao CRITICAL — exigem confirmacao explicita todas as vezes.
pc_lock/pc_sleep sao HIGH — exigem confirmacao.

NUNCA "lembrar" uma confirmacao anterior para pular a proxima.
"""

from __future__ import annotations

import math
import os
import platform
import shutil
import subprocess
import time
from typing import Any

_IS_WINDOWS = os.name == "nt"


class PCControl:
    """Controle remoto do PC (Windows via PowerShell; Linux via systemd/loginctl).

    Todos os comandos passam por SecurityGate.
    shutdown/restart sempre exigem confirmacao.
    """

    def __init__(self) -> None:
        self._last_action: str = ""
        self._last_result: dict[str, Any] | None = None
        self._real_execution: bool = False  # Safe default — True only in production

    @property
    def last_result(self) -> dict[str, Any] | None:
        return self._last_result

    def _run_ps(self, cmd: str, timeout: int = 15) -> dict[str, Any]:
        """Executa comando PowerShell no PC.

        NEVER executes real commands when _real_execution is False.
        """
        if not getattr(self, "_real_execution", False):
            return {"ok": False, "error": "real execution disabled (use _real_execution=True)"}
        try:
            start = time.time()
            result = subprocess.run(
                ["powershell", "-Command", cmd],
                capture_output=True, text=True, timeout=timeout,
            )
            duration = int((time.time() - start) * 1000)
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout.strip()[:2000],
                "stderr": result.stderr.strip()[:1000],
                "duration_ms": duration,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _run_argv(self, argv: list[str], timeout: int = 15) -> dict[str, Any]:
        """Executa um comando Linux (sem shell).

        Mesma trava de segurança do ``_run_ps``: não executa nada de verdade
        enquanto ``_real_execution`` for False.
        """
        if not getattr(self, "_real_execution", False):
            return {"ok": False, "error": "real execution disabled (use _real_execution=True)"}
        if shutil.which(argv[0]) is None:
            return {"ok": False, "error": f"{argv[0]} não encontrado neste sistema"}
        try:
            start = time.time()
            result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            duration = int((time.time() - start) * 1000)
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout.strip()[:2000],
                "stderr": result.stderr.strip()[:1000],
                "duration_ms": duration,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _delay_minutes(timeout_s: int) -> str:
        """O ``shutdown`` do Linux só aceita atraso em minutos (``+N``) ou ``now``."""
        return f"+{math.ceil(timeout_s / 60)}" if timeout_s > 0 else "now"

    def pc_status(self) -> dict[str, Any]:
        """Status do PC (SAFE - sem confirmacao)."""
        if not _IS_WINDOWS:
            return {
                "ok": True,
                "stdout": f"{platform.node()} | {platform.system()} {platform.release()} | {platform.machine()}",
            }
        return self._run_ps(
            "Get-ComputerInfo | Select-Object CsName,WindowsVersion,"
            "OsArchitecture,PowerStatus | ConvertTo-Json"
        )

    def pc_shutdown(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Desliga o PC (CRITICAL - requer confirmacao).

        Params:
            _confirmed: bool — deve ser True para executar
            force: bool — forca desligamento (default: False)
            timeout_s: int — segundos antes de desligar (default: 0)
        """
        params = params or {}
        if not params.get("_confirmed"):
            return {
                "ok": False,
                "requires_confirmation": True,
                "action": "pc_shutdown",
                "message": "pc_shutdown is CRITICAL. Set _confirmed=true to proceed.",
            }

        force = bool(params.get("force"))
        timeout_s = int(params.get("timeout_s", 0))

        self._last_action = "shutdown"
        if not _IS_WINDOWS:
            if timeout_s > 0:
                argv = ["shutdown", "-h", self._delay_minutes(timeout_s)]
            else:
                argv = ["systemctl", "poweroff"] + (["--force"] if force else [])
            result = self._run_argv(argv, timeout=10)
            self._last_result = result
            return result

        # (antes: f"Stop-Computer -Force{'/f'}" gerava "-Force/f", inválido no PowerShell)
        cmd = "Stop-Computer" + (" -Force" if force else "")
        if timeout_s > 0:
            cmd = f"shutdown /s {'/f ' if force else ''}/t {timeout_s}"
        result = self._run_ps(cmd, timeout=10)
        self._last_result = result
        return result

    def pc_restart(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Reinicia o PC (CRITICAL - requer confirmacao).

        Params:
            _confirmed: bool — deve ser True para executar
            force: bool — forca reinicio (default: False)
            timeout_s: int — segundos antes de reiniciar (default: 0)
        """
        params = params or {}
        if not params.get("_confirmed"):
            return {
                "ok": False,
                "requires_confirmation": True,
                "action": "pc_restart",
                "message": "pc_restart is CRITICAL. Set _confirmed=true to proceed.",
            }

        force = bool(params.get("force"))
        timeout_s = int(params.get("timeout_s", 0))

        self._last_action = "restart"
        if not _IS_WINDOWS:
            if timeout_s > 0:
                argv = ["shutdown", "-r", self._delay_minutes(timeout_s)]
            else:
                argv = ["systemctl", "reboot"] + (["--force"] if force else [])
            result = self._run_argv(argv, timeout=10)
            self._last_result = result
            return result

        cmd = "Restart-Computer" + (" -Force" if force else "")
        if timeout_s > 0:
            cmd = f"shutdown /r {'/f ' if force else ''}/t {timeout_s}"
        result = self._run_ps(cmd, timeout=10)
        self._last_result = result
        return result

    def pc_lock(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Bloqueia o PC (HIGH - requer confirmacao)."""
        params = params or {}
        if not params.get("_confirmed"):
            return {
                "ok": False,
                "requires_confirmation": True,
                "action": "pc_lock",
                "message": "pc_lock requires confirmation. Set _confirmed=true to proceed.",
            }

        self._last_action = "lock"
        if not _IS_WINDOWS:
            result = self._run_argv(["loginctl", "lock-session"], timeout=10)
            self._last_result = result
            return result
        result = self._run_ps(
            "rundll32.exe user32.dll,LockWorkStation",
            timeout=10,
        )
        self._last_result = result
        return result

    def pc_sleep(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Suspender o PC (HIGH - requer confirmacao)."""
        params = params or {}
        if not params.get("_confirmed"):
            return {
                "ok": False,
                "requires_confirmation": True,
                "action": "pc_sleep",
                "message": "pc_sleep requires confirmation. Set _confirmed=true to proceed.",
            }

        self._last_action = "sleep"
        if not _IS_WINDOWS:
            result = self._run_argv(["systemctl", "suspend"], timeout=10)
            self._last_result = result
            return result
        result = self._run_ps(
            "Add-Type -Assembly System.Windows.Forms; "
            "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)",
            timeout=10,
        )
        self._last_result = result
        return result

    def status(self) -> dict[str, Any]:
        """Status do PC Control."""
        return {
            "last_action": self._last_action,
            "last_result": self._last_result,
        }


_pc_control: PCControl | None = None


def get_pc_control() -> PCControl:
    global _pc_control
    if _pc_control is None:
        _pc_control = PCControl()
    return _pc_control


def execute_pc_control(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa acao de controle do PC."""
    ctrl = get_pc_control()
    if action == "pc_status":
        return ctrl.pc_status()
    elif action == "pc_shutdown":
        return ctrl.pc_shutdown(params)
    elif action == "pc_restart":
        return ctrl.pc_restart(params)
    elif action == "pc_lock":
        return ctrl.pc_lock(params)
    elif action == "pc_sleep":
        return ctrl.pc_sleep(params)
    else:
        return {"ok": False, "error": f"Unknown action: {action}"}
