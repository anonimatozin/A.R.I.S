"""ESP32 Hardware Manager do A.R.I.S.

Gerencia comunicação WebSocket com ESP32, controle de LEDs,
detecção de botão e estados visuais.

Arquitetura:
  ARIS → HardwareManager → WebSocket → ESP32
  ESP32 → WebSocket → HardwareManager → ARIS Event System
"""

import asyncio
import importlib.util
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from config.esp32_config import ESP32Config
from utils.logger import Logger

# ── Estados do Sistema ──────────────────────────────────────

class SystemState(Enum):
    """Estados visuais do ARIS."""
    INITIALIZING = "initializing"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    EXECUTING = "executing"
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    OFFLINE = "offline"
    ESP32_DISCONNECTED = "esp32_disconnected"


# ── Cores e Efeitos ─────────────────────────────────────────

@dataclass
class LEDColor:
    """Cor RGB + brilho."""
    r: int = 0
    g: int = 0
    b: int = 0
    brightness: int = 80

    def to_dict(self) -> dict:
        return {"r": self.r, "g": self.g, "b": self.b, "brightness": self.brightness}

    @classmethod
    def from_hex(cls, hex_color: str, brightness: int = 80) -> "LEDColor":
        h = hex_color.lstrip("#")
        return cls(r=int(h[0:2], 16), g=int(h[2:4], 16), b=int(h[4:6], 16), brightness=brightness)


# Paleta de cores para estados
STATE_COLORS = {
    SystemState.INITIALIZING:     LEDColor(r=0, g=0, b=255),      # Azul pulsando
    SystemState.IDLE:             LEDColor(r=0, g=50, b=100),     # Azul escuro
    SystemState.LISTENING:        LEDColor(r=0, g=255, b=0),      # Verde
    SystemState.THINKING:         LEDColor(r=255, g=150, b=0),    # Laranja pulsando
    SystemState.SPEAKING:         LEDColor(r=0, g=200, b=255),    # Ciano
    SystemState.EXECUTING:        LEDColor(r=255, g=255, b=0),    # Amarelo
    SystemState.SUCCESS:          LEDColor(r=0, g=255, b=0),      # Verde (flash)
    SystemState.ERROR:            LEDColor(r=255, g=0, b=0),      # Vermelho
    SystemState.WARNING:          LEDColor(r=255, g=100, b=0),    # Laranja
    SystemState.OFFLINE:          LEDColor(r=0, g=0, b=0),        # Apagado
    SystemState.ESP32_DISCONNECTED: LEDColor(r=255, g=0, b=0),    # Vermelho fixo
}

# Efeitos por estado
STATE_EFFECTS = {
    SystemState.INITIALIZING: "pulse",
    SystemState.IDLE: "solid",
    SystemState.LISTENING: "solid",
    SystemState.THINKING: "pulse",
    SystemState.SPEAKING: "pulse",
    SystemState.EXECUTING: "blink",
    SystemState.SUCCESS: "flash",
    SystemState.ERROR: "blink",
    SystemState.WARNING: "blink",
    SystemState.OFFLINE: "solid",
    SystemState.ESP32_DISCONNECTED: "solid",
}


# ── Mapeamento de botão → ação ──────────────────────────────

BUTTON_ACTIONS = {
    "single_click": "voice_toggle",
    "double_click": "stop_speaking",
    "triple_click": "turbo_mode",
    "quad_click": "config_action",
    "long_press": "reconnect",
}


# ── Wi-Fi do Mini Deck ──────────────────────────────────────

ESTADOS_WIFI = frozenset({"portal", "connecting", "connected", "failed"})


def parse_wifi_status(data: dict) -> dict:
    """Normaliza uma mensagem ``wifi_status`` vinda do deck.

    Só estes campos passam adiante (log/listeners/status): se o firmware
    mandasse algo extra por engano — ex.: uma senha — ele não sairia daqui.
    """
    return {
        "estado": str(data.get("estado", "")).lower(),
        "ip": str(data.get("ip", "")),
        "rssi": data.get("rssi"),
        "tentativa": data.get("tentativa"),
        "erro": str(data.get("erro", ""))[:120],
        "recebido_em": time.time(),
    }


# ── Hardware Manager ────────────────────────────────────────

class HardwareManager:
    """Gerencia hardware ESP32 conectado ao ARIS.

    Funcionalidades:
    - WebSocket server para receber conexões do ESP32
    - Controle de LEDs (esquerdo, direito, ambos)
    - Detecção de botão com debounce e múltiplos cliques
    - Sistema de estados visuais
    - Heartbeat e reconexão automática
    - Modo simulação para desenvolvimento
    """

    def __init__(self, config: ESP32Config, logger: Logger | None = None):
        self._config = config
        self._logger = logger
        self._connected = False
        self._available = True
        self._esp32_ws = None
        self._current_state = SystemState.INITIALIZING
        self._lock = threading.Lock()

        # Callbacks para ações do botão
        self._button_callbacks: dict[str, Callable] = {}

        # Listeners de eventos do deck (ex.: wifi_status do Mini Deck)
        self._event_listeners: list[Callable[[str, dict], None]] = []
        self._wifi_status: dict | None = None

        # Beacon UDP: o deck descobre o IP deste PC por broadcast
        self._beacon_thread: threading.Thread | None = None

        # Estado dos LEDs
        self._left_color = LEDColor()
        self._right_color = LEDColor()

        # Thread do WebSocket server
        self._server_thread: threading.Thread | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

        # Heartbeat
        self._last_heartbeat = 0.0
        self._heartbeat_thread: threading.Thread | None = None

        # Estatísticas
        self._stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "button_events": 0,
            "reconnections": 0,
            "errors": 0,
        }

        if self._config.simulation:
            self._log("Modo simulação ativo — sem hardware real")

    # ── Lifecycle ───────────────────────────────────────────

    def start(self) -> str:
        """Inicia o WebSocket server."""
        if not self._config.enabled:
            self._available = False
            return "ESP32 desabilitado (ESP32_ENABLED=false) - hardware indisponível"

        if self._config.simulation:
            self._connected = True
            self._available = True
            self._current_state = SystemState.IDLE
            self._log("Simulação iniciada - ESP32 fake conectado")
            return "ESP32 em modo simulação"

        try:
            if importlib.util.find_spec("websockets") is None:
                raise ImportError("websockets")
            self._running = True
            self._available = True
            self._server_thread = threading.Thread(target=self._run_server, daemon=True)
            self._server_thread.start()
            self._log(f"WebSocket server iniciando em ws://{self._config.ws_host}:{self._config.ws_port}")
            if self._config.beacon_port > 0:
                self._beacon_thread = threading.Thread(target=self._run_beacon, daemon=True)
                self._beacon_thread.start()
                self._log(
                    f"Beacon UDP a cada {self._config.beacon_interval:.1f}s "
                    f"na porta {self._config.beacon_port} (deck acha o PC)"
                )
            return f"ESP32 server iniciando em porta {self._config.ws_port}"
        except ImportError:
            self._available = False
            self._connected = False
            return ("Hardware ESP32 indisponível: biblioteca 'websockets' não instalada. "
                    "Execute: pip install websockets")

    def stop(self) -> None:
        """Para o WebSocket server e desconecta."""
        self._running = False
        self._connected = False
        self._current_state = SystemState.OFFLINE
        self._log("Hardware Manager desligado")

    def _run_server(self) -> None:
        """Executa o WebSocket server em thread separada."""
        import websockets
        import websockets.sync.server

        async def handler(websocket):
            self._esp32_ws = websocket
            self._connected = True
            self._last_heartbeat = time.time()
            self._log("ESP32 CONECTADO")

            # Enviar estado atual
            await self._send_state(self._current_state)

            try:
                async for message in websocket:
                    await self._on_message(message)
            except Exception as e:
                self._log(f"Erro na comunicação: {e}")
            finally:
                self._connected = False
                self._esp32_ws = None
                self._log("ESP32 DESCONECTADO")

        async def main():
            self._loop = asyncio.get_running_loop()
            async with websockets.serve(handler, self._config.ws_host, self._config.ws_port):
                await asyncio.Future()  # run forever

        try:
            asyncio.run(main())
        except Exception as e:
            self._log(f"Server error: {e}")

    # ── Beacon UDP ───────────────────────────────────────────

    @staticmethod
    def _beacon_payload(ws_port: int) -> dict:
        """Payload do beacon UDP (o deck usa para achar este PC)."""
        return {"beacon": "aris", "ws_port": ws_port}

    def _run_beacon(self) -> None:
        """Broadcast UDP periódico: o deck descobre o IP deste PC com ele.

        Funciona tanto na rede da casa quanto no AP do deck (modo portal),
        porque o broadcast alcança as duas interfaces conforme o link.
        """
        import socket

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError as e:
            self._log(f"Beacon UDP indisponível: {e}")
            return

        payload = json.dumps(self._beacon_payload(self._config.ws_port)).encode()
        destino = ("255.255.255.255", self._config.beacon_port)
        erro_logado = False
        while self._running:
            try:
                sock.sendto(payload, destino)
                erro_logado = False
            except OSError as e:
                if not erro_logado:
                    self._log(f"Beacon UDP falhou ({e}) — o deck não acharia o PC sozinho")
                    erro_logado = True
            time.sleep(self._config.beacon_interval)
        sock.close()

    # ── Comunicação ─────────────────────────────────────────

    async def _send_state(self, state: SystemState) -> None:
        """Envia estado atual para o ESP32."""
        await self._send({"tipo": "estado", "estado": state.value})

    async def _send(self, data: dict) -> bool:
        """Envia JSON para o ESP32."""
        if not self._connected or not self._esp32_ws:
            if not self._config.simulation:
                return False
            # Em simulação, apenas log
            self._log(f"SIMULADO → {json.dumps(data)}")
            self._stats["messages_sent"] += 1
            return True

        try:
            await self._esp32_ws.send(json.dumps(data))
            self._stats["messages_sent"] += 1
            return True
        except Exception as e:
            self._log(f"Erro ao enviar: {e}")
            self._stats["errors"] += 1
            return False

    def _send_sync(self, data: dict) -> bool:
        """Envio síncrono (bloqueia até completar)."""
        if self._config.simulation:
            self._log(f"SIMULADO -> {json.dumps(data)}")
            self._stats["messages_sent"] += 1
            return True

        if not self._connected or not self._esp32_ws or not self._loop:
            return False

        try:
            future = asyncio.run_coroutine_threadsafe(self._send(data), self._loop)
            result = future.result(timeout=5.0)
            self._stats["messages_sent"] += 1
            return result
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e) or repr(e)
            self._log(f"Erro ao enviar [{error_type}]: {error_msg}")
            self._stats["errors"] += 1
            return False

    async def _on_message(self, raw: str) -> None:
        """Processa mensagem recebida do ESP32."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._log(f"Mensagem inválida: {raw[:100]}")
            return

        self._stats["messages_received"] += 1
        msg_type = data.get("tipo", "")

        if msg_type == "heartbeat":
            self._last_heartbeat = time.time()
            await self._send({"tipo": "heartbeat_ack"})

        elif msg_type == "button":
            action = data.get("action", "")
            self._log(f"BOTÃO: {action}")
            self._stats["button_events"] += 1
            self._handle_button(action)

        elif msg_type == "connected":
            self._connected = True
            self._last_heartbeat = time.time()
            self._log("ESP32 confirmou conexão")

        elif msg_type == "wifi_status":
            info = parse_wifi_status(data)
            self._wifi_status = info
            extra = f" ip={info['ip']}" if info["ip"] else ""
            self._log(f"WiFi do deck: {info['estado']}{extra}")
            self._notify_event("wifi_status", info)

        elif msg_type == "error":
            self._log(f"ESP32 erro: {data.get('message', 'desconhecido')}")

    # ── Controle de LEDs ────────────────────────────────────

    def set_left_led(self, color: LEDColor) -> None:
        """Define cor do LED esquerdo."""
        self._left_color = color
        if not (self._connected or self._config.simulation):
            return  # ESP32 indisponível/desconectado: sem log falso
        self._send_sync({
            "tipo": "led",
            "target": "left",
            "r": color.r, "g": color.g, "b": color.b,
            "brightness": color.brightness,
        })
        self._log(f"LED LEFT -> RGB({color.r},{color.g},{color.b})")

    def set_right_led(self, color: LEDColor) -> None:
        """Define cor do LED direito."""
        self._right_color = color
        if not (self._connected or self._config.simulation):
            return
        self._send_sync({
            "tipo": "led",
            "target": "right",
            "r": color.r, "g": color.g, "b": color.b,
            "brightness": color.brightness,
        })
        self._log(f"LED RIGHT -> RGB({color.r},{color.g},{color.b})")

    def set_both_leds(self, color: LEDColor) -> None:
        """Define cor de ambos os LEDs."""
        self._left_color = color
        self._right_color = color
        if not (self._connected or self._config.simulation):
            return
        self._send_sync({
            "tipo": "led",
            "target": "both",
            "r": color.r, "g": color.g, "b": color.b,
            "brightness": color.brightness,
        })
        self._log(f"LED BOTH -> RGB({color.r},{color.g},{color.b})")

    def set_effect(self, target: str, effect: str) -> None:
        """Aplica efeito a um LED (blink, pulse, fade, flash)."""
        if not (self._connected or self._config.simulation):
            return
        self._send_sync({
            "tipo": "efeito",
            "target": target,
            "efeito": effect,
        })

    def turn_off_leds(self) -> None:
        """Apaga todos os LEDs."""
        self.set_both_leds(LEDColor(r=0, g=0, b=0, brightness=0))

    # ── Sistema de Estados ──────────────────────────────────

    def set_state(self, state: SystemState) -> None:
        """Muda o estado visual do ARIS."""
        if state == self._current_state:
            return

        old_state = self._current_state
        self._current_state = state

        color = STATE_COLORS.get(state, LEDColor())
        effect = STATE_EFFECTS.get(state, "solid")

        # LED esquerdo = estado interno
        self.set_left_led(color)

        # LED direito = estado de interação (mais brilhante)
        interaction_color = LEDColor(
            r=color.r, g=color.g, b=color.b,
            brightness=min(255, color.brightness + 40),
        )
        self.set_right_led(interaction_color)

        # Aplicar efeito
        if effect != "solid":
            self.set_effect("both", effect)

        self._log(f"Estado: {old_state.value} -> {state.value}")

    def flash_success(self) -> None:
        """Flash verde de confirmação."""
        self.set_both_leds(LEDColor(r=0, g=255, b=0, brightness=100))
        threading.Timer(0.5, lambda: self.set_state(self._current_state)).start()

    def flash_error(self) -> None:
        """Flash vermelho de erro."""
        self.set_both_leds(LEDColor(r=255, g=0, b=0, brightness=100))
        threading.Timer(0.5, lambda: self.set_state(self._current_state)).start()

    # ── Botão ───────────────────────────────────────────────

    def register_button_action(self, action_name: str, callback: Callable) -> None:
        """Registra callback para uma ação do botão."""
        self._button_callbacks[action_name] = callback

    def _handle_button(self, action: str) -> None:
        """Despacha ação do botão para o callback correspondente."""
        action_name = BUTTON_ACTIONS.get(action, action)
        callback = self._button_callbacks.get(action_name)

        if callback:
            try:
                threading.Thread(target=callback, daemon=True).start()
            except Exception as e:
                self._log(f"Erro ao executar ação '{action_name}': {e}")
        else:
            self._log(f"Ação '{action_name}' não registrada")

    def register_event_listener(self, callback: Callable[[str, dict], None]) -> None:
        """Registra callback de eventos do deck (ex.: wifi_status)."""
        self._event_listeners.append(callback)

    def _notify_event(self, event: str, data: dict) -> None:
        """Despacha um evento do deck para os listeners (thread própria)."""
        for callback in list(self._event_listeners):
            try:
                threading.Thread(target=callback, args=(event, data), daemon=True).start()
            except Exception as e:
                self._log(f"Erro ao notificar evento '{event}': {e}")

    # ── Heartbeat ───────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        """Loop de heartbeat para detectar desconexão."""
        while self._running:
            time.sleep(self._config.heartbeat_interval)

            if not self._connected:
                continue

            # Verificar timeout
            if time.time() - self._last_heartbeat > self._config.heartbeat_timeout:
                self._log("Heartbeat timeout — ESP32 possivelmente desconectado")
                self._connected = False
                self._current_state = SystemState.ESP32_DISCONNECTED
                self._try_reconnect()
                continue

            # Enviar ping
            self._send_sync({"tipo": "heartbeat"})

    def _try_reconnect(self) -> None:
        """Tenta reconectar ao ESP32."""
        self._stats["reconnections"] += 1
        self._log(f"Tentativa de reconexão #{self._stats['reconnections']}")

    # ── Utilidades ──────────────────────────────────────────

    def _log(self, msg: str) -> None:
        """Log com prefixo [HARDWARE]."""
        # Limpar caracteres não-ASCII para Windows console
        safe_msg = msg.encode("ascii", "replace").decode("ascii")
        if self._logger:
            self._logger.info(f"{self._config.log_prefix} {safe_msg}")
        else:
            print(f"  {self._config.log_prefix} {safe_msg}")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def available(self) -> bool:
        """Indica se o subsistema de hardware está disponível.

        False quando o ESP32 está desabilitado ou a biblioteca
        ``websockets`` não está instalada (sem simulação de logs).
        """
        return self._available

    @property
    def state(self) -> SystemState:
        return self._current_state

    def get_status(self) -> dict:
        """Retorna status completo do hardware."""
        return {
            "available": self._available,
            "connected": self._connected,
            "simulation": self._config.simulation,
            "state": self._current_state.value,
            "left_led": {"r": self._left_color.r, "g": self._left_color.g, "b": self._left_color.b},
            "right_led": {"r": self._right_color.r, "g": self._right_color.g, "b": self._right_color.b},
            "stats": self._stats.copy(),
            "last_heartbeat": self._last_heartbeat,
            "wifi": dict(self._wifi_status) if self._wifi_status else None,
            "ws_url": f"ws://{self._config.ws_host}:{self._config.ws_port}",
        }

    def format_status(self) -> str:
        """Formata status para exibição."""
        status = self.get_status()
        conn = "ONLINE" if status["connected"] else "OFFLINE"
        sim = " (SIM)" if status["simulation"] else ""
        wifi = status.get("wifi")
        if wifi:
            wifi_txt = wifi["estado"] + (f" ({wifi['ip']})" if wifi.get("ip") else "")
        else:
            wifi_txt = "nunca visto"

        lines = [
            f"Hardware Manager{sim}",
            f"   Status: {conn}",
            f"   Estado: {status['state']}",
            f"   WS: {status['ws_url']}",
            f"   WiFi deck: {wifi_txt}",
            f"   LED Left:  RGB({status['left_led']['r']},{status['left_led']['g']},{status['left_led']['b']})",
            f"   LED Right: RGB({status['right_led']['r']},{status['right_led']['g']},{status['right_led']['b']})",
            f"   Msgs: down={status['stats']['messages_received']} up={status['stats']['messages_sent']}",
            f"   Buttons: {status['stats']['button_events']}",
            f"   Reconnections: {status['stats']['reconnections']}",
        ]
        return "\n".join(lines)
