"""Cliente minimo para comandar os olhos a partir de QUALQUER programa Python (ex.: o sistema da ARIS).

So usa a biblioteca padrao (nada de Qt), entao pode ser importado no ambiente da ARIS:

    from aris_eyes.client import send
    send("mood thinking")     # -> "ok"   (ou None se os olhos nao estiverem rodando)

Comandos aceitos: veja HELP em `aris_eyes/api.py` ou o README.
"""
from __future__ import annotations

import socket
from typing import Optional

from .config import control_socket_path


def send(command: str, timeout: float = 1.0, path: Optional[str] = None) -> Optional[str]:
    """Envia um comando e devolve a resposta. Devolve None se os olhos nao estiverem rodando."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(path or control_socket_path())
        sock.sendall((command.strip() + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8", "replace").strip()
    except OSError:          # inclui timeout, socket inexistente e conexao recusada
        return None
    finally:
        sock.close()


def is_running(path: Optional[str] = None) -> bool:
    return send("ping", path=path) == "pong"
