"""Canal de controle: um socket Unix local que recebe comandos de uma linha.

Serve a dois propositos:
  1. Atalhos GLOBAIS: o atalho do seu desktop roda `aris-eyes.sh --send toggle` (X11 e Wayland).
  2. Integracao com a ARIS: o sistema principal manda `mood thinking`, `speech 0.6`, etc.

Seguranca: o socket fica em XDG_RUNTIME_DIR (so o seu usuario acessa) e so existe uma lista fixa
de comandos; nunca executa comando de shell.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger("aris_eyes.control")

MAX_LINE = 1024


class ControlServer(QObject):
    def __init__(self, handler: Callable[[str], str], path: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._handler = handler
        self._path = path
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)

    def start(self) -> bool:
        QLocalServer.removeServer(self._path)           # limpa socket velho de uma execucao que caiu
        if not self._server.listen(self._path):
            log.warning("nao consegui abrir o canal de controle em %s: %s",
                        self._path, self._server.errorString())
            return False
        return True

    def stop(self) -> None:
        self._server.close()
        QLocalServer.removeServer(self._path)

    def _on_connection(self) -> None:
        while True:
            sock = self._server.nextPendingConnection()
            if sock is None:
                return
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(sock.deleteLater)

    def _on_ready(self, sock: QLocalSocket) -> None:
        while sock.canReadLine():
            line = bytes(sock.readLine(MAX_LINE + 2)).decode("utf-8", "replace").strip()
            if not line:
                continue
            if len(line) > MAX_LINE:
                reply = "erro: comando longo demais"
            else:
                try:
                    reply = self._handler(line)
                except Exception as exc:                # um comando ruim nunca derruba os olhos
                    log.exception("falha ao executar %r", line)
                    reply = f"erro: {exc}"
            sock.write((reply + "\n").encode("utf-8"))
            sock.flush()
        if sock.bytesAvailable() > 4 * MAX_LINE:         # lixo sem quebra de linha: desconecta
            sock.disconnectFromServer()
