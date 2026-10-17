"""Heartbeat CLL1 — monitora conexao e mantem estado sincronizado.

Executa em background (daemon thread). Envia heartbeat periodico
para o CLL1 e mantem estado local sobre a conexao.
"""

from __future__ import annotations

import platform
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from utils.logger import Logger


class CLL1Status(StrEnum):
    """Status possivel da conexao CLL1."""

    ONLINE = "online"
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ERROR = "error"


@dataclass
class CLL1State:
    """Estado da conexao CLL1 (local)."""

    status: CLL1Status = CLL1Status.OFFLINE
    last_heartbeat: str = ""
    last_response: dict[str, Any] = field(default_factory=dict)
    consecutive_failures: int = 0
    total_heartbeats: int = 0
    total_failures: int = 0


class CLL1Heartbeat:
    """Heartbeat periodico para o CLL1.

    Envia heartbeat em daemon thread. Se CLL1 cair,
    marca como offline e tenta reconexao controlada.
    """

    PROTOCOL_VERSION = "2.0.0"

    def __init__(
        self,
        client: Any,
        node_id: str = "aris-pc",
        interval: float = 30.0,
        logger: Logger | None = None,
    ) -> None:
        # client=None: cria o CLL1Client interno via env vars (como o
        # chamador em core/aris.py assume). Sem isso, _do_heartbeat batia
        # em "'NoneType' object has no attribute 'heartbeat_status'".
        if client is None:
            try:
                from core.cll1_client import CLL1Client

                client = CLL1Client()
            except Exception:
                client = None
        self._client = client
        self._node_id = node_id
        self._interval = max(5.0, interval)
        self._logger = logger
        self._state = CLL1State()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> CLL1State:
        with self._lock:
            return CLL1State(
                status=self._state.status,
                last_heartbeat=self._state.last_heartbeat,
                last_response=dict(self._state.last_response),
                consecutive_failures=self._state.consecutive_failures,
                total_heartbeats=self._state.total_heartbeats,
                total_failures=self._state.total_failures,
            )

    @property
    def is_online(self) -> bool:
        return self.state.status == CLL1Status.ONLINE

    def start(self) -> None:
        """Inicia o heartbeat em daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="cll1-heartbeat",
            daemon=True,
        )
        self._thread.start()

        if self._logger:
            self._logger.info(
                f"CLL1 Heartbeat iniciado (intervalo: {self._interval}s)"
            )

    def stop(self) -> None:
        """Para o heartbeat de forma controlada."""
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        with self._lock:
            self._state.status = CLL1Status.OFFLINE

        if self._logger:
            self._logger.info("CLL1 Heartbeat parado")

    def send_now(self) -> dict[str, Any]:
        """Envia heartbeat imediatamente (sincrono)."""
        return self._do_heartbeat()

    def _loop(self) -> None:
        """Loop principal do heartbeat (executa em thread)."""
        if self._logger:
            self._logger.info(f"CLL1 Heartbeat loop iniciado (intervalo: {self._interval}s)")
        while not self._stop_event.is_set():
            self._do_heartbeat()
            self._stop_event.wait(self._interval)
        if self._logger:
            self._logger.info("CLL1 Heartbeat loop encerrado")

    def _do_heartbeat(self) -> dict[str, Any]:
        """Executa um heartbeat e atualiza estado."""
        now = datetime.now(UTC).isoformat()

        with self._lock:
            self._state.total_heartbeats += 1
            self._state.status = CLL1Status.CONNECTING

        try:
            self._get_pc_status()

            response = self._client.heartbeat_status()

            with self._lock:
                self._state.status = CLL1Status.ONLINE
                self._state.last_heartbeat = now
                self._state.last_response = response
                self._state.consecutive_failures = 0

            if self._logger:
                self._logger.debug(
                    f"CLL1 Heartbeat OK: {response.get('ok', False)} (total: {self._state.total_heartbeats})"
                )

            return response

        except Exception as e:
            with self._lock:
                self._state.status = CLL1Status.OFFLINE
                self._state.consecutive_failures += 1
                self._state.total_failures += 1
                self._state.last_heartbeat = now

            if self._logger:
                self._logger.warning(
                    f"CLL1 Heartbeat falhou "
                    f"(tentativa {self._state.consecutive_failures}/{self._state.total_failures} total): {e}"
                )

            return {"ok": False, "error": str(e)}

    @staticmethod
    def _get_pc_status() -> str:
        """Retorna status basico do PC."""
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            return f"cpu={cpu}% mem={mem.percent}% os={platform.system()}"
        except ImportError:
            return f"os={platform.system()}"
        except Exception:
            return f"os={platform.system()}"
