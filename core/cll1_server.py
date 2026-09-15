"""CLL1 Server — server TCP no PC que aceita conexoes do CLL1.

Gerencia autenticacao, recebimento de mensagens, envio de respostas,
e sincronizacao de estado entre PC e CLL1.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
import uuid
from collections.abc import Callable

from utils.logger import Logger

PROTOCOL_VERSION = "2.0.0"
MAX_MESSAGE_SIZE = 20 * 1024 * 1024
AUTH_WINDOW_SECONDS = 60


def _send_json(sock: socket.socket, data: dict) -> None:
    """Envia JSON com prefixo de 8 bytes (big-endian)."""
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack(">Q", len(raw)))
    sock.sendall(raw)


def _recv_json(sock: socket.socket) -> dict:
    """Recebe JSON com prefixo de 8 bytes (big-endian)."""
    size_data = b""
    while len(size_data) < 8:
        chunk = sock.recv(8 - len(size_data))
        if not chunk:
            raise ConnectionError("Conexao encerrada")
        size_data += chunk

    size = struct.unpack(">Q", size_data)[0]
    if size <= 0 or size > MAX_MESSAGE_SIZE:
        raise ValueError(f"Tamanho invalido: {size}")

    data = b""
    while len(data) < size:
        chunk = sock.recv(min(65536, size - len(data)))
        if not chunk:
            raise ConnectionError("Conexao encerrada")
        data += chunk

    return json.loads(data.decode("utf-8"))


class CLL1Server:
    """Server TCP que aceita conexoes autenticadas do CLL1.

    Args:
        host: Endereco para bind.
        port: Porta para bind.
        token: Token de autenticacao (ou carrega de env).
        logger: Logger opcional.
        on_message: Callback chamado quando uma mensagem chega.
            Assinatura: (text: str, origin_info: dict) -> str | None
            Retorna a resposta para enviar de volta ao CLL1.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        token: str | None = None,
        logger: Logger | None = None,
        on_message: Callable[[str, dict], str | None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._token = token or os.getenv("CLL1_TOKEN", "")
        self._logger = logger
        self._on_message = on_message
        self._server_socket: socket.socket | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._connections: dict[str, socket.socket] = {}
        self._lock = threading.Lock()
        self._authenticated: dict[str, float] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def connection_count(self) -> int:
        with self._lock:
            return len(self._connections)

    def start(self) -> None:
        """Inicia o server em daemon thread."""
        if self._running:
            return

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self._host, self._port))
        self._server_socket.listen(5)
        self._running = True

        self._thread = threading.Thread(
            target=self._accept_loop,
            name="cll1-server",
            daemon=True,
        )
        self._thread.start()

        if self._logger:
            self._logger.info(
                f"CLL1 Server iniciado em {self._host}:{self._port}"
            )

    def stop(self) -> None:
        """Para o server e fecha conexoes."""
        self._running = False

        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass

        with self._lock:
            for conn_id, sock in self._connections.items():
                try:
                    sock.close()
                except Exception:
                    pass
            self._connections.clear()
            self._authenticated.clear()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        if self._logger:
            self._logger.info("CLL1 Server parado")

    def send_to_cll1(self, conn_id: str, data: dict) -> bool:
        """Envia dados para uma conexao CLL1 especifica."""
        with self._lock:
            sock = self._connections.get(conn_id)
        if not sock:
            return False
        try:
            _send_json(sock, data)
            return True
        except Exception:
            return False

    def broadcast(self, data: dict) -> int:
        """Envia dados para todas as conexoes autenticadas."""
        sent = 0
        with self._lock:
            conns = list(self._connections.items())
        for conn_id, sock in conns:
            try:
                _send_json(sock, data)
                sent += 1
            except Exception:
                pass
        return sent

    def _accept_loop(self) -> None:
        """Loop de aceitacao de conexoes."""
        while self._running:
            try:
                if self._server_socket is None:
                    break
                client_sock, addr = self._server_socket.accept()
                conn_id = str(uuid.uuid4())[:12]
                t = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr, conn_id),
                    name=f"cll1-{conn_id}",
                    daemon=True,
                )
                t.start()
            except OSError:
                if self._running:
                    if self._logger:
                        self._logger.warning("CLL1 Server: erro ao aceitar conexao")
                break

    def _handle_client(
        self, sock: socket.socket, addr: tuple, conn_id: str
    ) -> None:
        """Gerencia uma conexao CLL1 individual."""
        if self._logger:
            self._logger.info(f"CLL1 conectou: {addr} (conn={conn_id})")

        try:
            first_msg = _recv_json(sock)

            if first_msg.get("type") == "auth":
                token = first_msg.get("token", "")
                ts = float(first_msg.get("ts", 0))

                if abs(time.time() - ts) > AUTH_WINDOW_SECONDS:
                    _send_json(sock, {"type": "auth_fail", "error": "timestamp_expired"})
                    sock.close()
                    return

                if not self._validate_token(token):
                    _send_json(sock, {"type": "auth_fail", "error": "invalid_token"})
                    sock.close()
                    return

                _send_json(sock, {"type": "auth_ok", "conn_id": conn_id})

                with self._lock:
                    self._connections[conn_id] = sock
                    self._authenticated[conn_id] = time.time()

            else:
                _send_json(sock, {"type": "auth_fail", "error": "expected_auth"})
                sock.close()
                return

            while self._running:
                msg = _recv_json(sock)

                if msg.get("type") == "msg":
                    token = msg.get("token", "")
                    ts = float(msg.get("ts", 0))
                    payload = msg.get("payload", {})

                    if abs(time.time() - ts) > AUTH_WINDOW_SECONDS:
                        _send_json(sock, {
                            "type": "msg_ack",
                            "ok": False,
                            "error": "timestamp_expired",
                        })
                        continue

                    if not self._validate_token(token):
                        _send_json(sock, {
                            "type": "msg_ack",
                            "ok": False,
                            "error": "invalid_token",
                        })
                        continue

                    text = payload.get("text", "")
                    origin_info = {
                        "source": payload.get("source", "cll1"),
                        "channel": f"tcp:{self._port}",
                        "user_id": payload.get("user_id", "cll1-device"),
                        "session_id": payload.get("session_id", ""),
                        "message_id": payload.get("message_id", str(uuid.uuid4())[:8]),
                        "conn_id": conn_id,
                    }

                    response = None
                    if self._on_message:
                        response = self._on_message(text, origin_info)

                    _send_json(sock, {
                        "type": "msg_ack",
                        "ok": True,
                        "response": response,
                        "message_id": payload.get("message_id", ""),
                    })

                elif msg.get("type") == "sync_push":
                    token = msg.get("token", "")
                    if not self._validate_token(token):
                        _send_json(sock, {"type": "sync_ack", "ok": False})
                        continue

                    pending = msg.get("pending", [])
                    if self._on_message:
                        self._on_message("__sync_push__", {"pending": pending})

                    _send_json(sock, {
                        "type": "sync_ack",
                        "ok": True,
                        "synced": len(pending),
                    })

                elif msg.get("type") == "sync_request":
                    _send_json(sock, {
                        "type": "sync_data",
                        "ok": True,
                        "personalidade_hash": "",
                        "pending": [],
                    })

                elif msg.get("type") == "heartbeat":
                    _send_json(sock, {
                        "type": "heartbeat_ack",
                        "ok": True,
                        "pc_status": "online",
                        "timestamp": time.time(),
                    })

                elif msg.get("type") == "disconnect":
                    break

        except (ConnectionError, ValueError) as e:
            if self._logger:
                self._logger.debug(f"CLL1 {conn_id} desconectou: {e}")
        except Exception as e:
            if self._logger:
                self._logger.warning(f"CLL1 {conn_id} erro: {e}")
        finally:
            with self._lock:
                self._connections.pop(conn_id, None)
                self._authenticated.pop(conn_id, None)
            try:
                sock.close()
            except Exception:
                pass
            if self._logger:
                self._logger.info(f"CLL1 {conn_id} encerrado")

    def _validate_token(self, token: str) -> bool:
        """Valida token de autenticacao."""
        if not self._token:
            return False
        return token == self._token
