"""Router — roteador PC online/offline para o CLL1.

Verifica se o PC esta acessivel e roteia mensagens para
a instancia apropriada (PC principal ou Edge).

Garantia: NUNCA ha duas instancias respondendo a mesma mensagem
simultaneamente. Durante transicao, uma unica instancia "tem a palavra".
"""

from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from edge.edge_chat import EdgeChat
from edge.edge_config import EdgeConfig
from utils.logger import Logger

try:
    from core.neural.mode import get_mode_manager, ARISMode
except ImportError:
    get_mode_manager = None
    ARISMode = None


@dataclass
class RouterState:
    """Estado do roteador."""
    pc_online: bool = False
    last_check: float = 0.0
    check_interval: float = 10.0
    consecutive_failures: int = 0
    instance: str = "edge"
    transitioning: bool = False
    last_mode_switch: float = 0.0


class Router:
    """Roteador de mensagens CLL1 com transicao segura.

    Regra: NUNCA duas instancias respondem simultaneamente.
    Durante transicao EDGE→PRIMARY ou PRIMARY→EDGE, uma unica
    instancia tem a palavra (definida por _active_owner).
    """

    TRANSITION_COOLDOWN = 5.0  # segundos entre transicoes

    def __init__(
        self,
        pc_host: str | None = None,
        pc_port: int | None = None,
        pc_token: str | None = None,
        logger: Logger | None = None,
        event_bus: object | None = None,
    ) -> None:
        self._pc_host = pc_host or os.getenv("CLL1_HOST", "192.168.0.106")
        self._pc_port = int(pc_port or os.getenv("CLL1_PORT", "8765"))
        self._pc_token = pc_token or os.getenv("CLL1_TOKEN", "")
        self._logger = logger
        self._event_bus = event_bus
        self._state = RouterState()
        self._edge: EdgeChat | None = None
        self._on_pc_message: Any = None
        self._active_owner: str = "edge"  # quem "tem a palavra"
        self._lock = threading.Lock()
        self._pending_messages: list[dict] = []

    @property
    def state(self) -> RouterState:
        return self._state

    @property
    def edge(self) -> EdgeChat:
        if self._edge is None:
            config = EdgeConfig.from_env()
            self._edge = EdgeChat(config)
        return self._edge

    @property
    def active_owner(self) -> str:
        """Quem esta respondendo agora ('edge' ou 'primary')."""
        return self._active_owner

    def set_pc_message_handler(self, handler: Any) -> None:
        """Define callback para enviar mensagens ao PC."""
        self._on_pc_message = handler

    def check_pc_online(self, force: bool = False) -> bool:
        """Verifica se o PC esta acessivel via TCP.

        Args:
            force: Se True, ignora o cache e faz check imediato.
        """
        now = time.time()
        if not force and now - self._state.last_check < self._state.check_interval:
            return self._state.pc_online

        self._state.last_check = now

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            result = sock.connect_ex((self._pc_host, self._pc_port))
            sock.close()

            if result == 0:
                was_offline = not self._state.pc_online
                self._state.pc_online = True
                self._state.consecutive_failures = 0
                self._state.instance = "primary"
                if was_offline:
                    self._start_transition("primary")
                    self._publish_event("pc_status", {"online": True, "mode": "primary"})
                self._update_mode_manager(True)
                return True
            else:
                self._state.consecutive_failures += 1
                if self._state.consecutive_failures >= 3:
                    was_online = self._state.pc_online
                    self._state.pc_online = False
                    self._state.instance = "edge"
                    if was_online:
                        self._start_transition("edge")
                        self._publish_event("pc_status", {"online": False, "mode": "edge"})
                self._update_mode_manager(self._state.pc_online)
                return self._state.pc_online

        except Exception:
            self._state.consecutive_failures += 1
            if self._state.consecutive_failures >= 3:
                was_online = self._state.pc_online
                self._state.pc_online = False
                self._state.instance = "edge"
                if was_online:
                    self._start_transition("edge")
                    self._publish_event("pc_status", {"online": False, "mode": "edge"})
            self._update_mode_manager(self._state.pc_online)
            return self._state.pc_online

    def _start_transition(self, new_owner: str) -> None:
        """Inicia transicao segura — lock para evitar respostas duplicadas."""
        with self._lock:
            now = time.time()
            if now - self._state.last_mode_switch < self.TRANSITION_COOLDOWN:
                return  # cooldown entre transicoes

            old_owner = self._active_owner
            self._state.transitioning = True
            self._active_owner = new_owner
            self._state.last_mode_switch = now

            if self._logger:
                self._logger.info(
                    f"Router: transicao {old_owner} → {new_owner}"
                )

            # Processar mensagens pendentes na nova instancia
            pending = list(self._pending_messages)
            self._pending_messages.clear()

            self._state.transitioning = False

        # Fora do lock: processar pendencias
        for msg in pending:
            try:
                self.route_message(msg["text"], msg["origin"])
            except Exception:
                pass

        # Publicar evento de transicao de modo
        self._publish_event("mode_transition", {"from": old_owner, "to": new_owner})

    def _publish_event(self, event_type: str, payload: dict) -> None:
        """Publica evento no event bus local para dashboard em tempo real."""
        if self._event_bus is not None:
            try:
                from core.neural.events import Event
                event = Event(
                    event_type=event_type,
                    source="router",
                    payload=payload,
                    priority=50,
                    confidence=1.0,
                )
                self._event_bus.publish(event)
            except Exception:
                pass

    def route_message(self, text: str, origin_info: dict) -> str:
        """Roteia mensagem com garantia de instancia unica.

        Durante transicao, a instancia antiga pode ainda ter mensagens
        pendentes — essas sao processadas pela nova instancia.
        """
        # Verificar se o usuário está contestando o estado do PC
        # Ex: "mas o PC está ligado", "o PC tá ligado sim", "PC tá online"
        text_lower = text.lower().strip()
        contest_keywords = [
            "mas o pc", "mas o computador", "o pc ta", "o pc está",
            "pc ta ligado", "pc está ligado", "computador ta ligado",
            "pc online", "pc ta online", "pc ligado", "ta ligado"
        ]
        is_contesting = any(kw in text_lower for kw in contest_keywords)
        
        if contest_keywords and any(kw in text_lower for kw in ["ligado", "online", "funcionando", "aceso"]):
            is_contesting = True
        
        # Se usuário contesta, forçar re-check imediato ignorando cache
        if is_contesting:
            self._logger.info(f"Usuário contestando estado do PC: '{text}' — forçando re-check")
            pc_online = self.check_pc_online(force=True)
            # Responder ao usuário com o estado real
            if pc_online:
                return "Você tem razão! O PC está **online** agora. O modo é PRIMARY."
            else:
                return "Verifiquei e o PC continua **offline**. Se acabou de ligar, aguarde alguns segundos para o heartbeat detectar."
        else:
            pc_online = self.check_pc_online()

        with self._lock:
            owner = self._active_owner
            if self._state.transitioning:
                self._pending_messages.append({"text": text, "origin": origin_info})
                return (
                    "Modo em transicao. Aguarde um momento e tente novamente."
                )

        if owner == "primary" and pc_online and self._on_pc_message:
            try:
                response = self._on_pc_message(text, origin_info)
                if response:
                    return response
            except Exception as e:
                if self._logger:
                    self._logger.warning(
                        f"PC falhou, fallback para edge: {e}"
                    )
                with self._lock:
                    self._state.pc_online = False
                    self._state.instance = "edge"
                    self._active_owner = "edge"

        return self.edge.respond(text, origin_info)

    def get_status(self) -> dict:
        """Retorna status do roteador."""
        return {
            "pc_online": self._state.pc_online,
            "instance": self._state.instance,
            "active_owner": self._active_owner,
            "transitioning": self._state.transitioning,
            "pc_host": self._pc_host,
            "pc_port": self._pc_port,
            "consecutive_failures": self._state.consecutive_failures,
            "edge_available": self.edge.available,
        }

    def _update_mode_manager(self, pc_online: bool) -> None:
        """Atualiza o ModeManager com base no heartbeat."""
        if get_mode_manager is None:
            return
        try:
            mm = get_mode_manager()
            mm.update_heartbeat(pc_online, reason="router_tcp")
        except Exception:
            pass
