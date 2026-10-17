"""Mini Deck Wi-Fi: parser/beacon no PC e reação do rosto (sem hardware).

Cobre o protocolo novo ``wifi_status`` (firmware -> HardwareManager ->
eyes_bridge -> rosto): allowlist de campos (senha nunca passa), beacon
UDP de descoberta do PC e o mapeamento portal/conectando/conectado/erro
para as expressões dos olhos.
"""

import asyncio
import json
import time

import pytest

from config.esp32_config import ESP32Config
from modules.esp32_hardware import ESTADOS_WIFI, HardwareManager, parse_wifi_status
from utils import eyes_bridge

# ── Ponte do rosto ──────────────────────────────────────────

class _CapturaSend:
    """Substitui eyes_bridge._client_send registrando os comandos."""

    def __init__(self, resposta: str | None = "ok"):
        self.comandos: list[str] = []
        self.resposta = resposta

    def __call__(self, command: str, timeout: float = 0.25):
        self.comandos.append(command)
        return self.resposta


@pytest.fixture
def captura(monkeypatch):
    """Ponte da ARIS isolada: sem olhos reais e sem autolaunch."""
    eyes_bridge.reset_for_tests()
    monkeypatch.setattr(eyes_bridge, "_enabled", lambda: True)
    monkeypatch.setattr(eyes_bridge, "_resolve_idle_mood", lambda: "neutral")
    monkeypatch.setattr(eyes_bridge, "autolaunch_enabled", lambda: False)
    fake = _CapturaSend()
    monkeypatch.setattr(eyes_bridge, "_client_send", fake)
    yield fake
    eyes_bridge.reset_for_tests()


class TestRostoWifi:
    def test_mapeamento_completo(self, captura):
        assert eyes_bridge.WIFI_FACES == {
            "portal": "surprised",
            "connecting": "thinking",
            "connected": "happy",
            "failed": "error",
        }
        for estado, mood in eyes_bridge.WIFI_FACES.items():
            eyes_bridge.reset_for_tests()
            captura.comandos.clear()
            assert eyes_bridge.set_wifi_face(estado) == "aplicado"
            assert captura.comandos == [f"state {mood}"]

    def test_estado_desconhecido_ignorado(self, captura):
        assert eyes_bridge.set_wifi_face("qualquercoisa") is None
        assert captura.comandos == []

    def test_reacao_pendente_ate_o_idle(self, captura):
        assert eyes_bridge.set_state("speaking") is True
        captura.comandos.clear()
        assert eyes_bridge.set_wifi_face("connected") == "pendente"
        assert captura.comandos == []              # não mexeu no rosto ocupado
        assert eyes_bridge.set_state("idle") is True
        assert "state neutral" in captura.comandos
        assert captura.comandos[-1] == "state happy"   # reação aplicada no idle

    def test_erro_assume_mesmo_ocupado(self, captura):
        assert eyes_bridge.set_state("speaking") is True
        captura.comandos.clear()
        assert eyes_bridge.set_wifi_face("failed", forcar=True) == "forçado"
        assert captura.comandos == ["state error"]

    def test_wifi_repetido_nao_reenvia(self, captura):
        assert eyes_bridge.set_wifi_face("connected") == "aplicado"
        captura.comandos.clear()
        assert eyes_bridge.set_wifi_face("connected") == "aplicado"
        assert captura.comandos == []              # mesmo mood: dedupe

    def test_olhos_parados_nao_levanta_nem_preso(self, captura):
        captura.resposta = None                    # olhos fora do ar
        assert eyes_bridge.set_wifi_face("connected") is None
        captura.resposta = "ok"                    # voltaram: nada ficou preso
        assert eyes_bridge.set_state("idle") is True


# ── Lado PC: parser e manager ───────────────────────────────

def _manager() -> HardwareManager:
    return HardwareManager(config=ESP32Config(enabled=True, simulation=False, beacon_port=0))


class TestParserWifiStatus:
    def test_campos_normais(self):
        info = parse_wifi_status({
            "tipo": "wifi_status",
            "estado": "CONNECTED",
            "ip": "192.168.0.115",
            "rssi": -58,
            "tentativa": 1,
        })
        assert info["estado"] == "connected"
        assert info["ip"] == "192.168.0.115"
        assert info["rssi"] == -58
        assert info["tentativa"] == 1
        assert isinstance(info["recebido_em"], float)

    def test_allowlist_bloqueia_extras(self):
        info = parse_wifi_status({"estado": "failed", "senha": "SEGREDO123"})
        assert set(info) == {"estado", "ip", "rssi", "tentativa", "erro", "recebido_em"}
        assert "SEGREDO123" not in json.dumps(info)

    def test_erro_truncado(self):
        info = parse_wifi_status({"estado": "failed", "erro": "x" * 500})
        assert len(info["erro"]) == 120


class TestHardwareWifiStatus:
    def test_status_vira_evento_para_os_listeners(self):
        hw = _manager()
        vistos: list[tuple] = []
        hw.register_event_listener(lambda ev, data: vistos.append((ev, data)))
        asyncio.run(hw._on_message(json.dumps({
            "tipo": "wifi_status", "estado": "connected", "ip": "10.0.0.5",
        })))
        deadline = time.time() + 2
        while not vistos and time.time() < deadline:
            time.sleep(0.01)
        assert vistos and vistos[0][0] == "wifi_status"
        assert vistos[0][1]["estado"] == "connected"
        assert hw._wifi_status["ip"] == "10.0.0.5"

    def test_status_do_deck_nao_vaza_senha(self):
        hw = _manager()
        asyncio.run(hw._on_message(json.dumps({
            "tipo": "wifi_status", "estado": "failed", "senha": "SEGREDO123",
        })))
        assert "SEGREDO123" not in json.dumps(hw.get_status())
        assert "SEGREDO123" not in hw.format_status()

    def test_json_invalido_nao_derruba(self):
        hw = _manager()
        asyncio.run(hw._on_message("{isso não é json"))
        assert hw._wifi_status is None


# ── Beacon UDP (descoberta do PC) ───────────────────────────

class TestBeacon:
    def test_payload(self):
        assert HardwareManager._beacon_payload(8766) == {"beacon": "aris", "ws_port": 8766}

    def test_config_padrao(self):
        config = ESP32Config()
        assert config.beacon_port == 8767
        assert config.beacon_interval > 0
        assert config.ws_host == "0.0.0.0"        # deck real precisa alcançar

    def test_estados_wifi_do_protocolo(self):
        assert ESTADOS_WIFI == frozenset({"portal", "connecting", "connected", "failed"})
