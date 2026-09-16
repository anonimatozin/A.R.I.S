"""Router — roteador PC online/offline para o CLL1.

Verifica se o PC esta acessivel e roteia mensagens para
a instancia apropriada (PC principal ou Edge).
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from typing import Any

from edge.edge_chat import EdgeChat
from edge.edge_config import EdgeConfig
from utils.logger import Logger


@dataclass
class RouterState:
    """Estado do roteador."""
    pc_online: bool = False
    last_check: float = 0.0
    check_interval: float = 10.0
    consecutive_failures: int = 0
    instance: str = "edge"


class Router:
    """Roteador de mensagens CLL1.

    Verifica periodicamente se o PC esta acessivel via TCP.
    Roteia mensagens para PC (quando online) ou Edge (quando offline).
    """

    def __init__(
        self,
        pc_host: str | None = None,
        pc_port: int | None = None,
        pc_token: str | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._pc_host = pc_host or os.getenv("CLL1_HOST", "192.168.0.106")
        self._pc_port = int(pc_port or os.getenv("CLL1_PORT", "8765"))
        self._pc_token = pc_token or os.getenv("CLL1_TOKEN", "")
        self._logger = logger
        self._state = RouterState()
        self._edge: EdgeChat | None = None
        self._on_pc_message: Any = None

    @property
    def state(self) -> RouterState:
        return self._state

    @property
    def edge(self) -> EdgeChat:
        if self._edge is None:
            config = EdgeConfig.from_env()
            self._edge = EdgeChat(config)
        return self._edge

    def set_pc_message_handler(self, handler: Any) -> None:
        """Define callback para enviar mensagens ao PC."""
        self._on_pc_message = handler

    def check_pc_online(self) -> bool:
        """Verifica se o PC esta acessivel via TCP."""
        now = time.time()
        if now - self._state.last_check < self._state.check_interval:
            return self._state.pc_online

        self._state.last_check = now

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            result = sock.connect_ex((self._pc_host, self._pc_port))
            sock.close()

            if result == 0:
                self._state.pc_online = True
                self._state.consecutive_failures = 0
                self._state.instance = "primary"
                return True
            else:
                self._state.consecutive_failures += 1
                if self._state.consecutive_failures >= 3:
                    self._state.pc_online = False
                    self._state.instance = "edge"
                return self._state.pc_online

        except Exception:
            self._state.consecutive_failures += 1
            if self._state.consecutive_failures >= 3:
                self._state.pc_online = False
                self._state.instance = "edge"
            return self._state.pc_online

    def route_message(self, text: str, origin_info: dict) -> str:
        """Roteia mensagem para PC ou Edge conforme estado.

        Args:
            text: Texto da mensagem.
            origin_info: Metadados de origem.

        Returns:
            Resposta da instancia apropriada.
        """
        pc_online = self.check_pc_online()

        if pc_online and self._on_pc_message:
            try:
                response = self._on_pc_message(text, origin_info)
                if response:
                    return response
            except Exception as e:
                if self._logger:
                    self._logger.warning(
                        f"PC falhou, fallback para edge: {e}"
                    )
                self._state.pc_online = False
                self._state.instance = "edge"

        return self.edge.respond(text, origin_info)

    def get_status(self) -> dict:
        """Retorna status do roteador."""
        return {
            "pc_online": self._state.pc_online,
            "instance": self._state.instance,
            "pc_host": self._pc_host,
            "pc_port": self._pc_port,
            "consecutive_failures": self._state.consecutive_failures,
            "edge_available": self.edge.available,
        }
