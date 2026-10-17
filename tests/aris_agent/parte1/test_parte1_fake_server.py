"""Servidor HTTP falso OpenAI-compatível para os testes da Parte 1.

Não tem ``test_*``: é só o dublê compartilhado (``FakeOpenAIServer``) usado
pelos demais arquivos de teste da pasta. Roda em ``127.0.0.1`` numa thread,
sem internet.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def completion(
    content: str = "ok",
    *,
    model: str = "modelo-teste",
    finish_reason: str = "stop",
    usage: dict | None = None,
) -> dict:
    """Corpo de 200 com uma resposta de texto normal."""
    return {
        "id": "cmpl-fake",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage
        or {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
    }


def tool_call_completion(
    name: str,
    arguments: str = "{}",
    *,
    model: str = "modelo-teste",
    call_id: str = "call_1",
    usage: dict | None = None,
) -> dict:
    """Corpo de 200 com ``tool_calls`` (``arguments`` como string JSON)."""
    body = completion("", model=model, finish_reason="tool_calls", usage=usage)
    body["choices"][0]["message"] = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }
    return body


def error(
    status: int = 400,
    message: str = "bad request",
    *,
    code: str | None = None,
    failed_generation: object = None,
) -> tuple[int, dict, dict]:
    """``(status, corpo, headers)`` no formato de erro OpenAI/Groq."""
    error_body: dict = {"message": message, "type": "invalid_request_error"}
    if code is not None:
        error_body["code"] = code
    if failed_generation is not None:
        error_body["failed_generation"] = failed_generation
    return status, {"error": error_body}, {}


def rate_limit(retry_after: str = "2") -> tuple[int, dict, dict]:
    return 429, {"error": {"message": "rate limit", "type": "rate_limit_exceeded"}}, {
        "Retry-After": retry_after
    }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass  # cliente desistiu (teste de timeout)

    def do_POST(self) -> None:  # noqa: N802 - nome definido pelo http.server
        server: FakeOpenAIServer = self.server  # type: ignore[assignment]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        server.requests.append(
            {"path": self.path, "headers": dict(self.headers), "body": parsed}
        )
        status, payload, headers = server.next_response()
        data = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # cliente desistiu (teste de timeout)

    def do_GET(self) -> None:  # noqa: N802 - nome definido pelo http.server
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass  # silencioso nos testes


class FakeOpenAIServer(ThreadingHTTPServer):
    """Servidor local com fila de respostas ``enqueue(...)`` e registro de requests."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.queue: deque[tuple[int, dict, dict, float]] = deque()
        self.requests: list[dict] = []
        self._thread: threading.Thread | None = None

    def enqueue(
        self,
        status: int = 200,
        payload: dict | None = None,
        headers: dict | None = None,
        delay: float = 0.0,
    ) -> None:
        """Empilha a próxima resposta (status int ou tupla ``error()``)."""
        if isinstance(status, tuple):  # conveniência: enqueue(error(...))
            status, payload, headers = status  # type: ignore[misc]
        self.queue.append(
            (status, payload if payload is not None else {}, headers or {}, delay)
        )

    def next_response(self) -> tuple[int, dict, dict]:
        if not self.queue:
            return 500, {"error": {"message": "sem roteiro no servidor falso"}}, {}
        status, payload, headers, delay = self.queue.popleft()
        if delay:
            time.sleep(delay)
        return status, payload, headers

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"

    @property
    def request_count(self) -> int:
        return len(self.requests)

    def start(self) -> FakeOpenAIServer:
        self._thread = threading.Thread(
            target=self.serve_forever, args=(0.02,), daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> FakeOpenAIServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def free_port() -> int:
    """Porta local livre (para testar conexão recusada)."""
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
