"""Windows Service wrapper for A.R.I.S. Local Agent.

Instalacao:
    python -m agent.windows_service install

Inicializacao:
    net start ARISAgent

Parada:
    net stop ARISAgent

Remocao:
    python -m agent.windows_service remove
"""

from __future__ import annotations

import os
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil


class ARISAgentService(win32serviceutil.ServiceFramework):
    """Servico Windows do A.R.I.S. Local Agent."""

    _svc_name_ = "ARISAgent"
    _svc_display_name_ = "A.R.I.S. Local Agent"
    _svc_description_ = "A.R.I.S. background agent - persistent AI assistant"
    _svc_dependencies_ = ["Netman"]

    def __init__(self, args) -> None:
        win32serviceutil.ServiceFramework.__init__(self, args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._agent = None

    def SvcStop(self) -> None:  # noqa: N802
        """Para o servico."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self._stop_event)
        if self._agent:
            self._agent.stop()

    def SvcDoRun(self) -> None:  # noqa: N802
        """Executa o servico."""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self._main()

    def _main(self) -> None:
        """Loop principal do servico."""
        from agent.service import ARISService

        self._agent = ARISService()
        if not self._agent.start():
            return

        # Esperar sinal de parada
        while True:
            result = win32event.WaitForSingleObject(self._stop_event, 5000)
            if result == win32event.WAIT_OBJECT_0:
                break

        self._agent.stop()


def install() -> None:
    """Instala o servico Windows."""
    python_exe = sys.executable
    service_script = os.path.abspath(__file__)

    # Registrar servico
    import win32serviceutil
    win32serviceutil.InstallService(
        python_exe,
        [python_exe, service_script],
        "ARISAgent",
        "A.R.I.S. Local Agent",
        "A.R.I.S. background agent",
    )
    print("Servico instalado com sucesso!")
    print("Para iniciar: net start ARISAgent")


def remove() -> None:
    """Remove o servico Windows."""
    try:
        import win32serviceutil
        win32serviceutil.RemoveService("ARISAgent")
        print("Servico removido.")
    except Exception as e:
        print(f"Erro ao remover: {e}")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(ARISAgentService)
