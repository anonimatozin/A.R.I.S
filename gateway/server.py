"""Gateway server — TCP + HTTP for CLL1 Control Center."""

from __future__ import annotations

import json
import os
import socket
import struct
import threading

from gateway.auth import init_auth
from gateway.core import CoreOps
from gateway.web import start_http_server
from gateway.events import set_event_bus

MAX_REQUEST_SIZE = 20 * 1024 * 1024


def send_json(sock: socket.socket, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!Q", len(payload)))
    sock.sendall(payload)


def recv_json(sock: socket.socket) -> dict:
    size_data = b""
    while len(size_data) < 8:
        chunk = sock.recv(8 - len(size_data))
        if not chunk:
            raise ConnectionError("Connection closed")
        size_data += chunk

    size = struct.unpack("!Q", size_data)[0]
    if size == 0 or size > MAX_REQUEST_SIZE:
        raise ValueError(f"Invalid size: {size}")

    data = b""
    while len(data) < size:
        chunk = sock.recv(min(65536, size - len(data)))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk

    return json.loads(data.decode("utf-8"))


def handle_client(
    sock: socket.socket,
    address: tuple,
    core: CoreOps,
) -> None:
    try:
        request = recv_json(sock)
        response = core.dispatch(request)
        send_json(sock, response)
    except Exception as e:
        try:
            send_json(sock, {"ok": False, "error": str(e)})
        except Exception:
            pass
    finally:
        sock.close()


def run_gateway(
    base_dir: str,
    host: str = "0.0.0.0",
    tcp_port: int = 8765,
    http_port: int = 8766,
    event_bus: object | None = None,
    logger: object | None = None,
) -> None:
    db_path = os.path.join(base_dir, "data", "aris.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # Initialize version tracking
    try:
        from core.version import initialize_version
        initialize_version()
    except Exception:
        pass

    if event_bus is not None:
        set_event_bus(event_bus, logger)

    init_auth(base_dir)
    core = CoreOps(base_dir, db_path)

    http_server = start_http_server(base_dir, host, http_port)
    http_thread = threading.Thread(
        target=http_server.serve_forever,
        name="http-server",
        daemon=True,
    )
    http_thread.start()
    print(f"HTTP server started on {host}:{http_port}")

    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp_sock.bind((host, tcp_port))
    tcp_sock.listen(20)
    print(f"TCP server started on {host}:{tcp_port}")

    try:
        while True:
            sock, addr = tcp_sock.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(sock, addr, core),
                daemon=True,
            )
            thread.start()
    except KeyboardInterrupt:
        pass
    finally:
        http_server.shutdown()
        tcp_sock.close()
