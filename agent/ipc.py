"""IPC — comunicacao local segura entre processos A.R.I.S.

Usa named pipes no Windows para comunicacao local.
O Agent recebe comandos e retorna respostas.
"""

from __future__ import annotations

import json
import struct
import threading
from collections.abc import Callable

PIPE_NAME = r"\\.\pipe\aris_agent"
BUFFER_SIZE = 65536


class IPCServer:
    """Servidor IPC via named pipe.

    Escuta por conexoes e processa mensagens do CLI/Outros processos.
    """

    def __init__(self, handler: Callable[[dict], dict] | None = None) -> None:
        self._handler = handler
        self._running = False
        self._thread: threading.Thread | None = None
        self._pipe = None

    def start(self) -> None:
        """Inicia o servidor IPC em thread separada."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Para o servidor IPC."""
        self._running = False
        if self._pipe:
            try:
                import ctypes
                ctypes.windll.kernel32.CancelIoEx(self._pipe, None)
            except Exception:
                pass

    def _run(self) -> None:
        """Loop principal do servidor."""
        while self._running:
            try:
                self._pipe = self._create_pipe()
                if self._pipe is None:
                    import time
                    time.sleep(1)
                    continue

                # Esperar conexao
                connected = self._wait_for_connection()
                if not connected:
                    continue

                # Processar mensagens
                self._handle_client()
            except Exception:
                import time
                time.sleep(1)

    def _create_pipe(self):
        """Cria o named pipe."""
        try:
            import ctypes

            pipe_handle = ctypes.windll.kernel32.CreateNamedPipeW(
                PIPE_NAME,
                0x00000003,  # PIPE_ACCESS_DUPLEX
                0x00000000,  # PIPE_TYPE_BYTE
                1,           # max instances
                BUFFER_SIZE,
                BUFFER_SIZE,
                0,           # default timeout
                None,        # security attributes
            )
            if pipe_handle == -1:
                return None
            return pipe_handle
        except Exception:
            return None

    def _wait_for_connection(self) -> bool:
        """Espera por conexao no pipe."""
        try:
            import ctypes
            result = ctypes.windll.kernel32.ConnectNamedPipe(self._pipe, None)
            return result or ctypes.windll.kernel32.GetLastError() == 535  # ERROR_PIPE_CONNECTED
        except Exception:
            return False

    def _handle_client(self) -> None:
        """Processa mensagens do cliente conectado."""
        import ctypes

        while self._running:
            try:
                # Ler tamanho da mensagem
                size_bytes = self._read(4)
                if size_bytes is None:
                    break
                size = struct.unpack("!I", size_bytes)[0]
                if size > BUFFER_SIZE:
                    break

                # Ler mensagem
                data = self._read(size)
                if data is None:
                    break

                message = json.loads(data.decode("utf-8"))
                response = self._process(message)
                self._send_response(response)
            except Exception:
                break

        try:
            import ctypes
            ctypes.windll.kernel32.DisconnectNamedPipe(self._pipe)
        except Exception:
            pass

    def _read(self, n: int) -> bytes | None:
        """Le bytes do pipe."""
        import ctypes
        import ctypes.wintypes as wintypes
        buf = ctypes.create_string_buffer(n)
        bytes_read = wintypes.DWORD()
        result = ctypes.windll.kernel32.ReadFile(
            self._pipe, buf, n, ctypes.byref(bytes_read), None
        )
        if not result:
            return None
        return buf.raw[:bytes_read.value]

    def _send_response(self, response: dict) -> None:
        """Envia resposta via pipe."""
        data = json.dumps(response, ensure_ascii=False).encode("utf-8")
        size = struct.pack("!I", len(data))
        self._write(size + data)

    def _write(self, data: bytes) -> None:
        """Escreve bytes no pipe."""
        import ctypes
        import ctypes.wintypes as wintypes
        bytes_written = wintypes.DWORD()
        ctypes.windll.kernel32.WriteFile(
            self._pipe, data, len(data), ctypes.byref(bytes_written), None
        )

    def _process(self, message: dict) -> dict:
        """Processa mensagem recebida."""
        if self._handler:
            try:
                return self._handler(message)
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "no handler"}


class IPCClient:
    """Cliente IPC para enviar mensagens ao Agent."""

    def __init__(self) -> None:
        self._pipe = None

    def send(self, message: dict, timeout: float = 10.0) -> dict | None:
        """Envia mensagem ao Agent e retorna resposta."""
        import ctypes
        import ctypes.wintypes as wintypes

        try:
            self._pipe = ctypes.windll.kernel32.CreateFileW(
                PIPE_NAME,
                0xC0000000,  # GENERIC_READ | GENERIC_WRITE
                0,           # no sharing
                None,        # default security
                3,           # OPEN_EXISTING
                0,           # default attributes
                None,        # no template
            )
            if self._pipe == -1:
                return None

            # Enviar
            data = json.dumps(message, ensure_ascii=False).encode("utf-8")
            size = struct.pack("!I", len(data))
            bytes_written = wintypes.DWORD()
            ctypes.windll.kernel32.WriteFile(
                self._pipe, size + data, len(size) + len(data),
                ctypes.byref(bytes_written), None
            )

            # Receber
            size_bytes = self._read(4)
            if size_bytes is None:
                return None
            resp_size = struct.unpack("!I", size_bytes)[0]
            resp_data = self._read(resp_size)
            if resp_data is None:
                return None

            return json.loads(resp_data.decode("utf-8"))
        except Exception:
            return None
        finally:
            if self._pipe and self._pipe != -1:
                ctypes.windll.kernel32.CloseHandle(self._pipe)

    def _read(self, n: int) -> bytes | None:
        import ctypes
        import ctypes.wintypes as wintypes
        buf = ctypes.create_string_buffer(n)
        bytes_read = wintypes.DWORD()
        result = ctypes.windll.kernel32.ReadFile(
            self._pipe, buf, n, ctypes.byref(bytes_read), None
        )
        if not result:
            return None
        return buf.raw[:bytes_read.value]
