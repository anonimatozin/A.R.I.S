"""Utilitários dos testes da Parte 3: contexto e servidor HTTP local.

Sem internet: os testes sobem um servidor em 127.0.0.1 e liberam o loopback
apenas via ``test_allow_local`` (chave de configuração só para testes).
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from aris_agent.config import AgentConfig
from aris_agent.contract.types import ToolContext

HTML_ARTIGO = """<!doctype html>
<html><head><meta charset="utf-8"><title>Artigo de Teste</title></head>
<body>
<nav><a href="/">Início</a> <a href="/sobre">Sobre</a></nav>
<article><h1>Título do Artigo</h1>
<p>Este é o parágrafo principal do artigo de teste, com texto suficiente para o
extrator reconhecê-lo como o corpo da página e descartar menus e rodapés.</p>
<p>Segundo parágrafo com mais conteúdo relevante sobre pesquisas e leitura de
páginas da web dentro do projeto A.R.I.S., a assistente do Vinicius.</p>
</article>
<footer>Rodapé do site</footer>
</body></html>
"""


def make_ctx(tmp_path: Path, *, allow_local: bool = True, web: dict | None = None) -> ToolContext:
    """ToolContext com seção ``web`` pronta para os testes."""
    section: dict = {}
    if allow_local:
        section["test_allow_local"] = True
    if web:
        section.update(web)
    config = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        sections={"web": section} if section else {},
    )
    return ToolContext(session_id="parte3", workdir=tmp_path, config=config, cancel=threading.Event())


def _handler_for(routes: dict) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:  # silencioso
            pass

        def do_GET(self) -> None:  # noqa: N802 - API do http.server
            route = routes.get(self.path)
            if route is None:
                body = b"404 nao encontrado"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            status, headers, body = route
            headers = dict(headers)
            no_length = headers.pop("X-No-Length", None)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            if not no_length:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


@contextlib.contextmanager
def local_server(routes: dict) -> Iterator[str]:
    """Sobe um servidor HTTP em 127.0.0.1:porta-efêmera; devolve a base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(routes))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
