"""Wake-on-LAN — liga o PC remotamente via magic packet.

NUNCA automatico — so mediante pedido explicito do usuario + confirmacao
explicita antes de executar. Configuracao em .env/.config, nunca hardcoded.

Fluxo: A.R.I.S. Edge → SecurityGate → Wake-on-LAN → PC inicia →
       A.R.I.S. Primary inicia → heartbeat → handshake → EDGE vira PRIMARY
"""

from __future__ import annotations

import os
import socket
import struct
import time
from typing import Any


class WakeOnLan:
    """Envia magic packet para ligar um PC remotamente.

    Configuracao via variaveis de ambiente:
        WOL_MAC_ADDRESS: MAC address do PC (ex: AA:BB:CC:DD:EE:FF)
        WOL_BROADCAST: endereco de broadcast (default: 255.255.255.255)
        WOL_PORT: porta UDP (default: 9)
        WOL_INTERFACE: interface de rede (opcional)
        WOL_TIMEOUT: timeout para verificacao online apos envio (default: 30s)
        WOL_MAX_ATTEMPTS: numero maximo de tentativas (default: 3)
    """

    def __init__(self) -> None:
        self._mac_address = os.getenv("WOL_MAC_ADDRESS", "")
        self._broadcast = os.getenv("WOL_BROADCAST", "255.255.255.255")
        self._port = int(os.getenv("WOL_PORT", "9"))
        self._timeout = int(os.getenv("WOL_TIMEOUT", "30"))
        self._max_attempts = int(os.getenv("WOL_MAX_ATTEMPTS", "3"))
        self._last_attempt: float = 0.0
        self._last_result: dict[str, Any] | None = None

    @property
    def configured(self) -> bool:
        """Se WoL esta configurado (MAC address definido)."""
        return bool(self._mac_address)

    @property
    def last_result(self) -> dict[str, Any] | None:
        return self._last_result

    def _parse_mac(self, mac: str) -> bytes:
        """Converte MAC address para bytes."""
        mac = mac.replace(":", "").replace("-", "").replace(".", "")
        if len(mac) != 12:
            raise ValueError(f"Invalid MAC address: {mac}")
        return bytes.fromhex(mac)

    def _build_magic_packet(self, mac_bytes: bytes) -> bytes:
        """Construi magic packet: 6 bytes 0xFF + 16x MAC address."""
        return b"\xff" * 6 + mac_bytes * 16

    def send_magic_packet(self, mac: str | None = None) -> dict[str, Any]:
        """Envia magic packet para ligar o PC.

        Args:
            mac: MAC address (usa config se nao fornecido).

        Returns:
            Resultado do envio.
        """
        target_mac = mac or self._mac_address
        if not target_mac:
            return {"ok": False, "error": "MAC address not configured"}

        try:
            mac_bytes = self._parse_mac(target_mac)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        magic = self._build_magic_packet(mac_bytes)

        sent = 0
        errors = []
        for attempt in range(self._max_attempts):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(magic, (self._broadcast, self._port))
                sock.close()
                sent += 1
            except Exception as e:
                errors.append(str(e))

        self._last_attempt = time.time()
        result = {
            "ok": sent > 0,
            "sent": sent,
            "total_attempts": self._max_attempts,
            "mac": target_mac,
            "broadcast": self._broadcast,
            "port": self._port,
        }
        if errors:
            result["errors"] = errors
        self._last_result = result
        return result

    def check_if_online(self, pc_host: str, pc_port: int = 8765,
                        timeout: float = 3.0) -> bool:
        """Verifica se o PC esta online apos WoL."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((pc_host, pc_port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def wake_and_wait(self, pc_host: str, pc_port: int = 8765) -> dict[str, Any]:
        """Envia WoL e espera o PC ficar online.

        Returns:
            Resultado com status final.
        """
        if not self.configured:
            return {"ok": False, "error": "WoL not configured (WOL_MAC_ADDRESS not set)"}

        # Enviar magic packet
        send_result = self.send_magic_packet()
        if not send_result["ok"]:
            return send_result

        # Esperar PC ficar online
        start = time.time()
        online = False
        checks = 0
        while time.time() - start < self._timeout:
            checks += 1
            if self.check_if_online(pc_host, pc_port):
                online = True
                break
            time.sleep(2)

        elapsed = int((time.time() - start) * 1000)
        result = {
            "ok": online,
            "sent": send_result["sent"],
            "mac": send_result["mac"],
            "elapsed_ms": elapsed,
            "checks": checks,
            "timeout_s": self._timeout,
        }

        if online:
            result["message"] = "PC is now online"
        else:
            result["message"] = f"PC did not come online within {self._timeout}s"

        self._last_result = result
        return result

    def status(self) -> dict[str, Any]:
        """Status do WoL."""
        return {
            "configured": self.configured,
            "mac_configured": bool(self._mac_address),
            "broadcast": self._broadcast,
            "port": self._port,
            "timeout": self._timeout,
            "max_attempts": self._max_attempts,
            "last_attempt": self._last_attempt,
            "last_result": self._last_result,
        }


_wol: WakeOnLan | None = None


def get_wol() -> WakeOnLan:
    global _wol
    if _wol is None:
        _wol = WakeOnLan()
    return _wol


def execute_wol(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa Wake-on-LAN via ToolExecutor.

    Params:
        mac: MAC address (opcional, usa config)
        wait: Se deve esperar PC ficar online (default: False)
        pc_host: Host do PC para verificacao
        pc_port: Porta do PC para verificacao
    """
    params = params or {}
    wol = get_wol()

    mac = params.get("mac")
    wait = params.get("wait", False)

    if wait:
        pc_host = params.get("pc_host", os.getenv("CLL1_HOST", "192.168.0.106"))
        pc_port = int(params.get("pc_port", os.getenv("CLL1_PORT", "8765")))
        return wol.wake_and_wait(pc_host, pc_port)

    return wol.send_magic_packet(mac)
