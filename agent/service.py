"""A.R.I.S. Local Agent — processo em segundo plano.

Rodando como servico Windows ou processo background.
 ponto de presenca local da A.R.I.S.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from agent.instance import InstanceManager
from agent.session import SessionManager


class ARISService:
    """Servico principal do A.R.I.S. Local Agent.

    Gerencia:
    - Instancia unica
    - Sessao ativa (60s timeout)
    - IPC (named pipe)
    - Gateway TCP/HTTP (CLL1)
    - Discord Bot
    - Heartbeat
    """

    def __init__(self) -> None:
        self._instance = InstanceManager()
        self._session = SessionManager(timeout=60.0)
        self._running = False
        self._ipc_server = None
        self._gateway_thread = None
        self._router = None
        self._discord_bot = None
        self._heartbeat = None
        self._on_message: Any = None

    @property
    def session(self) -> SessionManager:
        return self._session

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Inicia o servico.

        Returns:
            True se iniciou com sucesso.
        """
        if not self._instance.acquire():
            pid = self._instance.get_running_pid()
            print(f"A.R.I.S. ja esta rodando (PID: {pid})")
            return False

        self._running = True
        self._setup_signal_handlers()

        # Iniciar IPC
        from agent.ipc import IPCServer
        self._ipc_server = IPCServer(handler=self._handle_ipc)
        self._ipc_server.start()

        # Iniciar Gateway + Router + Discord
        self._start_gateway()

        # Iniciar loop de sessao
        self._session_thread = threading.Thread(target=self._session_loop, daemon=True)
        self._session_thread.start()

        return True

    def stop(self) -> None:
        """Para o servico."""
        self._running = False
        if self._ipc_server:
            self._ipc_server.stop()
        self._instance.release()

    def process_message(self, text: str, source: str = "cli") -> str:
        """Processa mensagem do usuario.

        Ativa sessao e roteia para a instancia correta.
        """
        self._session.activate()

        # Roteamento: PC online → PRIMARY, offline → EDGE
        if self._router:
            try:
                origin_info = {"source": source, "timestamp": time.time()}
                response = self._router.route_message(text, origin_info)
                return response
            except Exception as e:
                return f"Erro no roteamento: {e}"

        return "Servico nao inicializado completamente."

    def get_status(self) -> dict:
        """Status completo do servico."""
        return {
            "running": self._running,
            "pid": os.getpid(),
            "session": self._session.get_status(),
            "instance": self._instance.get_running_pid(),
        }

    def _start_gateway(self) -> None:
        """Inicia Gateway TCP + Router + Discord em threads."""
        try:
            from cll1.router import Router
            self._router = Router()
        except Exception:
            pass

        # Gateway TCP
        try:
            from gateway.server import run_gateway
            self._gateway_thread = threading.Thread(
                target=run_gateway, daemon=True,
                kwargs={"base_dir": str(Path(__file__).parent.parent)}
            )
            self._gateway_thread.start()
        except Exception:
            pass

        # Discord Bot
        try:
            if os.getenv("DISCORD_BOT_TOKEN"):
                from modules.discord_bot import DiscordBot
                self._discord_bot = DiscordBot()
                threading.Thread(target=self._discord_bot.run, daemon=True).start()
        except Exception:
            pass

    def _session_loop(self) -> None:
        """Loop que monitora timeout da sessao."""
        while self._running:
            time.sleep(5)
            if self._session.check_timeout():
                # Sessao expirou — voltou pra idle
                pass

    def _handle_ipc(self, message: dict) -> dict:
        """Handler para mensagens IPC."""
        cmd = message.get("command", "")

        if cmd == "status":
            return self.get_status()

        if cmd == "message":
            text = message.get("text", "")
            source = message.get("source", "ipc")
            response = self.process_message(text, source)
            return {"ok": True, "response": response}

        if cmd == "session":
            return self._session.get_status()

        if cmd == "stop":
            threading.Thread(target=self.stop).start()
            return {"ok": True, "message": "Stopping..."}

        return {"ok": False, "error": f"Unknown command: {cmd}"}

    def _setup_signal_handlers(self) -> None:
        """Registra handlers para sinais de sistema."""
        def shutdown_handler(signum, frame):
            self.stop()
            sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, shutdown_handler)
            signal.signal(signal.SIGINT, shutdown_handler)
        except (OSError, ValueError):
            pass
