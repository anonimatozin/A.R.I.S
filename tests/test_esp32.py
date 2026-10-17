"""Testes do Hardware Manager do A.R.I.S.

Testes unitários para o módulo ESP32.
"""

import asyncio
import json
import time
from unittest.mock import MagicMock

import pytest

from config.esp32_config import ESP32Config
from modules.esp32_hardware import (
    BUTTON_ACTIONS,
    STATE_COLORS,
    HardwareManager,
    LEDColor,
    SystemState,
)

# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def sim_config():
    """Configuração de simulação (sem hardware real)."""
    return ESP32Config(
        enabled=True,
        simulation=True,
        ws_port=8766,
        heartbeat_interval=1.0,
        heartbeat_timeout=5.0,
    )


@pytest.fixture
def disabled_config():
    """Configuração desabilitada."""
    return ESP32Config(enabled=False, simulation=False)


@pytest.fixture
def hw_manager(sim_config):
    """Hardware Manager em modo simulação."""
    return HardwareManager(config=sim_config)


# ── Testes de Configuração ──────────────────────────────────

class TestESP32Config:
    def test_default_config(self):
        config = ESP32Config()
        assert config.ws_port == 8766
        assert config.heartbeat_interval == 5.0
        assert config.button_single_click == "voice_toggle"

    def test_sim_config(self, sim_config):
        assert sim_config.simulation is True
        assert sim_config.enabled is True


# ── Testes de LEDColor ──────────────────────────────────────

class TestLEDColor:
    def test_default_color(self):
        color = LEDColor()
        assert color.r == 0
        assert color.g == 0
        assert color.b == 0
        assert color.brightness == 80

    def test_custom_color(self):
        color = LEDColor(r=255, g=100, b=50, brightness=100)
        assert color.r == 255
        assert color.g == 100
        assert color.b == 50

    def test_to_dict(self):
        color = LEDColor(r=255, g=0, b=0)
        d = color.to_dict()
        assert d["r"] == 255
        assert d["g"] == 0
        assert d["b"] == 0

    def test_from_hex(self):
        color = LEDColor.from_hex("#FF0080")
        assert color.r == 255
        assert color.g == 0
        assert color.b == 128


# ── Testes de SystemState ───────────────────────────────────

class TestSystemState:
    def test_all_states_have_colors(self):
        for state in SystemState:
            assert state in STATE_COLORS, f"Estado {state} sem cor definida"

    def test_all_states_have_actions(self):
        for action in BUTTON_ACTIONS.values():
            assert isinstance(action, str)


# ── Testes de HardwareManager ───────────────────────────────

class TestHardwareManager:
    def test_init_simulation(self, hw_manager):
        assert hw_manager._config.simulation is True
        assert hw_manager._connected is False

    def test_start_simulation(self, hw_manager):
        result = hw_manager.start()
        assert "simulação" in result
        assert hw_manager._connected is True
        assert hw_manager._current_state == SystemState.IDLE

    def test_stop(self, hw_manager):
        hw_manager.start()
        hw_manager.stop()
        assert hw_manager._connected is False
        assert hw_manager._current_state == SystemState.OFFLINE

    def test_set_state(self, hw_manager):
        hw_manager.start()
        hw_manager.set_state(SystemState.LISTENING)
        assert hw_manager._current_state == SystemState.LISTENING

    def test_set_leds_simulation(self, hw_manager):
        hw_manager.start()
        color = LEDColor(r=255, g=0, b=0)
        hw_manager.set_left_led(color)
        assert hw_manager._left_color.r == 255

        hw_manager.set_right_led(color)
        assert hw_manager._right_color.r == 255

    def test_turn_off_leds(self, hw_manager):
        hw_manager.start()
        hw_manager.set_both_leds(LEDColor(r=255, g=255, b=255))
        hw_manager.turn_off_leds()
        assert hw_manager._left_color.r == 0
        assert hw_manager._left_color.g == 0
        assert hw_manager._left_color.b == 0

    def test_format_status(self, hw_manager):
        hw_manager.start()
        status = hw_manager.format_status()
        assert "Hardware Manager" in status
        assert "ONLINE" in status

    def test_get_status(self, hw_manager):
        hw_manager.start()
        status = hw_manager.get_status()
        assert status["connected"] is True
        assert status["simulation"] is True
        assert status["state"] == "idle"

    def test_disabled_config(self, disabled_config):
        hw = HardwareManager(config=disabled_config)
        result = hw.start()
        assert "desabilitado" in result
        assert hw._connected is False


# ── Testes de Button Callback ───────────────────────────────

class TestButtonCallbacks:
    def test_register_callback(self, hw_manager):
        callback = MagicMock()
        hw_manager.register_button_action("test_action", callback)
        assert "test_action" in hw_manager._button_callbacks

    def test_handle_button_callback(self, hw_manager):
        callback = MagicMock()
        hw_manager.register_button_action("voice_toggle", callback)
        hw_manager._handle_button("single_click")
        time.sleep(0.1)  # Thread
        callback.assert_called()

    def test_handle_unknown_button(self, hw_manager):
        # Não deve levantar exceção
        hw_manager._handle_button("unknown_action")


# ── Testes de Mensagens ─────────────────────────────────────

class TestMessages:
    def test_on_message_invalid_json(self, hw_manager):
        hw_manager.start()
        # Não deve levantar exceção
        hw_manager._on_message("invalid json")

    def test_on_message_button(self, hw_manager):
        callback = MagicMock()
        hw_manager.register_button_action("voice_toggle", callback)
        hw_manager.start()

        msg = json.dumps({"tipo": "button", "action": "single_click"})
        asyncio.run(hw_manager._on_message(msg))
        time.sleep(0.1)
        callback.assert_called()

    def test_on_message_heartbeat(self, hw_manager):
        hw_manager.start()
        msg = json.dumps({"tipo": "heartbeat"})
        asyncio.run(hw_manager._on_message(msg))
        assert hw_manager._last_heartbeat > 0

    def test_stats_increment(self, hw_manager):
        hw_manager.start()
        initial = hw_manager._stats["messages_received"]
        msg = json.dumps({"tipo": "button", "action": "single_click"})
        asyncio.run(hw_manager._on_message(msg))
        assert hw_manager._stats["messages_received"] == initial + 1


# ── Testes de Safety (não deve crashar sem ESP32) ──────────

class TestSafety:
    def test_hw_manager_no_crash_without_esp32(self):
        config = ESP32Config(enabled=True, simulation=False)
        hw = HardwareManager(config=config)
        # Não deve crashar
        result = hw.start()
        assert isinstance(result, str)

    def test_send_sync_without_connection(self, hw_manager):
        # Em simulação, deve funcionar
        result = hw_manager._send_sync({"tipo": "test"})
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
