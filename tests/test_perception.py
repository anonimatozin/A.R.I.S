"""Testes da camada de percepção do A.R.I.S.

Cobre: base Sensor (ciclo de vida), eventos de percepção, níveis de
atenção, ponte de atenção (estado + memória episódica), os 7 sensores
(câmera, microfone, tela, sistema, arquivos, rede, hardware), o
PerceptionManager e a integração com handlers/rotas determinísticas.
"""

import pytest

from core.memory import MemoryManager
from core.neural.attention.attention_engine import AttentionEngine, AttentionLevel
from core.neural.event_bus import EventBus
from core.neural.events import (
    EVENT_CAMERA,
    EVENT_FILESYSTEM,
    EVENT_HARDWARE,
    EVENT_MICROPHONE,
    EVENT_NETWORK,
    EVENT_SCREEN_CHANGED,
    EVENT_SYSTEM_ALERT,
    EVENT_SYSTEM_METRIC,
    EVENT_USER_MESSAGE,
    EVENT_VOICE_COMMAND,
    PERCEPTION_EVENT_TYPES,
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    Event,
)
from core.neural.memory.system import MemorySystem
from core.neural.state import GlobalState
from core.perception.attention_bridge import AttentionBridge
from core.perception.camera_sensor import CameraSensor
from core.perception.config import PerceptionConfig
from core.perception.filesystem_sensor import FilesystemSensor
from core.perception.hardware_sensor import HardwareSensor
from core.perception.microphone_sensor import MicrophoneSensor
from core.perception.network_sensor import NetworkSensor
from core.perception.perception_manager import PerceptionManager
from core.perception.screen_sensor import ScreenSensor
from core.perception.sensor import Sensor
from core.perception.system_sensor import SystemSensor
from utils.logger import Logger


@pytest.fixture
def logger():
    return Logger(name="test-perception", level="CRITICAL")


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def attention():
    return AttentionEngine.with_defaults()


@pytest.fixture
def state():
    return GlobalState()


@pytest.fixture
def memory(logger, tmp_path):
    mm = MemoryManager(logger=logger, memory_root=tmp_path / "memory")
    return MemorySystem.build(mm, logger=logger, memory_root=tmp_path)


# ── Eventos de percepção ─────────────────────────────────────

class TestPerceptionEvents:
    def test_perception_types_registered(self):
        assert EVENT_CAMERA in PERCEPTION_EVENT_TYPES
        assert EVENT_MICROPHONE in PERCEPTION_EVENT_TYPES
        assert EVENT_SCREEN_CHANGED in PERCEPTION_EVENT_TYPES
        assert EVENT_FILESYSTEM in PERCEPTION_EVENT_TYPES
        assert EVENT_NETWORK in PERCEPTION_EVENT_TYPES
        assert EVENT_SYSTEM_METRIC in PERCEPTION_EVENT_TYPES
        assert EVENT_HARDWARE in PERCEPTION_EVENT_TYPES

    def test_user_message_not_perception(self):
        assert EVENT_USER_MESSAGE not in PERCEPTION_EVENT_TYPES


# ── Níveis de atenção ────────────────────────────────────────

class TestAttentionLevels:
    def test_level_classification(self):
        engine = AttentionEngine.with_defaults()
        assert engine.level(0.80) == AttentionLevel.CRITICAL
        assert engine.level(0.65) == AttentionLevel.HIGH
        assert engine.level(0.50) == AttentionLevel.NORMAL
        assert engine.level(0.25) == AttentionLevel.LOW
        assert engine.level(0.10) == AttentionLevel.IGNORE

    def test_camera_motion_classification(self):
        engine = AttentionEngine.with_defaults()
        event = Event(event_type=EVENT_CAMERA, source="camera",
                      payload={"text": "Movimento detectado"},
                      priority=PRIORITY_HIGH, confidence=0.7)
        scored, level = engine.classify(event)
        assert level in (AttentionLevel.HIGH, AttentionLevel.NORMAL)
        assert scored.score == engine.score(event).score

    def test_system_alert_high(self):
        engine = AttentionEngine.with_defaults()
        event = Event(event_type=EVENT_SYSTEM_ALERT, source="system",
                      payload={"text": "CPU crítica"},
                      priority=PRIORITY_CRITICAL, confidence=0.95)
        scored, level = engine.classify(event)
        assert level == AttentionLevel.CRITICAL

    def test_screen_change_low(self):
        engine = AttentionEngine.with_defaults()
        event = Event(event_type=EVENT_SCREEN_CHANGED, source="screen",
                      payload={"text": "Janela ativa"},
                      priority=PRIORITY_LOW, confidence=1.0)
        scored, level = engine.classify(event)
        assert level == AttentionLevel.LOW

    def test_attention_log(self):
        engine = AttentionEngine.with_defaults()
        event = Event(event_type=EVENT_CAMERA, source="camera",
                      payload={"text": "Movimento"}, priority=PRIORITY_HIGH)
        scored = engine.score(event)
        engine.note(scored)
        recent = engine.recent_attention()
        assert recent and recent[0]["event_type"] == EVENT_CAMERA
        assert "level" in recent[0]


# ── Estado global ────────────────────────────────────────────

class TestGlobalStatePerception:
    def test_update_perception(self):
        state = GlobalState()
        state.update_perception(enabled=True, active_sensors=2,
                                sensors={"camera": "disabled", "system": "running"})
        snap = state.snapshot()
        assert snap["perception"]["enabled"] is True
        assert snap["perception"]["active_sensors"] == 2
        assert snap["perception"]["sensors"]["system"] == "running"
        assert "Percepção" in state.describe()

    def test_attention_update(self):
        state = GlobalState()
        state.update_perception(last_attention="HIGH", attention_score=0.7,
                                attention_focus="Movimento")
        assert state.perception.last_attention == "HIGH"
        assert state.perception.attention_score == 0.7


# ── Base Sensor ──────────────────────────────────────────────

class DummySensor(Sensor):
    name = "dummy"

    def __init__(self, **kwargs):
        super().__init__(interval=0.5, **kwargs)
        self.calls = 0

    def sense(self):
        self.calls += 1
        return []


class UnavailableSensor(DummySensor):
    name = "unavailable"

    @property
    def available(self):
        return False


class TestSensorBase:
    def test_disabled_start_is_disabled(self):
        sensor = DummySensor(enabled=False)
        sensor.start()
        assert sensor.status == "disabled"
        sensor.stop()

    def test_unavailable_start_is_offline(self):
        sensor = UnavailableSensor(enabled=True)
        sensor.start()
        assert sensor.status == "offline"
        sensor.stop()

    def test_thread_start_stop(self):
        sensor = DummySensor(enabled=True)
        sensor.start()
        assert sensor.status == "running"
        sensor.stop()
        assert sensor.status in ("idle", "disabled")

    def test_run_once_publishes(self, bus):
        seen = []
        bus.subscribe("perception.event", lambda e: seen.append(e))
        sensor = DummySensor(event_bus=bus, enabled=True)
        sensor.sense = lambda: [sensor._make_event(payload={"text": "x"})]
        events = sensor.run_once()
        assert len(events) == 1
        assert len(seen) == 1

    def test_snapshot_shape(self):
        sensor = DummySensor(enabled=True)
        snap = sensor.snapshot()
        assert snap["name"] == "dummy"
        assert "status" in snap and "enabled" in snap


# ── Câmera ───────────────────────────────────────────────────

class TestCameraSensor:
    def test_offline_without_cv2(self, bus, monkeypatch):
        monkeypatch.setattr("core.perception.camera_sensor.HAS_CV2", False)
        sensor = CameraSensor(event_bus=bus, enabled=True)
        assert not sensor.available
        assert sensor.run_once() == []

    def test_disabled_emits_nothing(self, bus, monkeypatch):
        monkeypatch.setattr("core.perception.camera_sensor.HAS_CV2", False)
        sensor = CameraSensor(event_bus=bus, enabled=False)
        assert sensor.run_once() == []
        assert sensor.status != "running"

    def test_motion_detection(self, bus, monkeypatch):
        np = pytest.importorskip("numpy")
        monkeypatch.setattr("core.perception.camera_sensor.HAS_CV2", False)
        monkeypatch.setattr("core.perception.camera_sensor.HAS_NUMPY", True)
        sensor = CameraSensor(event_bus=bus, enabled=True,
                              motion_threshold=0.04)
        frame_a = np.zeros((20, 20), dtype=np.uint8)
        frame_b = np.full((20, 20), 255, dtype=np.uint8)
        assert sensor.test_frame(frame_a) == []
        events = sensor.test_frame(frame_b)
        assert len(events) == 1
        assert events[0].event_type == EVENT_CAMERA


# ── Microfone ────────────────────────────────────────────────

class TestMicrophoneSensor:
    def test_passive_state_update(self, bus, attention):
        sensor = MicrophoneSensor(event_bus=bus, enabled=True)
        sensor._subscribe_voice()
        bus.publish(Event(event_type=EVENT_USER_MESSAGE, source="voice",
                          payload={"text": "olá aris"}, confidence=0.9))
        assert sensor._speaking is True
        assert sensor._last_transcript == "olá aris"
        sensor._unsubscribe_voice()

    def test_no_duplication_by_default(self, bus):
        seen = []
        bus.subscribe(EVENT_MICROPHONE, lambda e: seen.append(e))
        sensor = MicrophoneSensor(event_bus=bus, enabled=True)  # relay=False
        sensor._subscribe_voice()
        bus.publish(Event(event_type=EVENT_VOICE_COMMAND, source="voice",
                          payload={"text": "timer"}, confidence=0.8))
        sensor._unsubscribe_voice()
        assert seen == []  # não re-emite eventos de voz

    def test_relay_emits_perception_event(self, bus):
        seen = []
        bus.subscribe(EVENT_MICROPHONE, lambda e: seen.append(e))
        sensor = MicrophoneSensor(event_bus=bus, enabled=True, relay=True)
        sensor._subscribe_voice()
        bus.publish(Event(event_type=EVENT_VOICE_COMMAND, source="voice",
                          payload={"text": "timer"}, confidence=0.8))
        sensor._unsubscribe_voice()
        assert len(seen) == 1
        assert seen[0].event_type == EVENT_MICROPHONE


# ── Tela ─────────────────────────────────────────────────────

class TestScreenSensor:
    def test_window_change_emits(self, bus, monkeypatch):
        sensor = ScreenSensor(event_bus=bus, enabled=True)
        monkeypatch.setattr(sensor, "_active_window", lambda: "Notepad")
        monkeypatch.setattr(sensor, "_window", "")
        events = sensor.sense()
        assert len(events) == 1
        assert events[0].event_type == EVENT_SCREEN_CHANGED
        assert events[0].payload["window"] == "Notepad"

    def test_no_repeat_same_window(self, bus, monkeypatch):
        sensor = ScreenSensor(event_bus=bus, enabled=True)
        monkeypatch.setattr(sensor, "_active_window", lambda: "Notepad")
        sensor._window = "Notepad"
        assert sensor.sense() == []

    def test_ocr_disabled_by_default(self, bus, monkeypatch):
        sensor = ScreenSensor(event_bus=bus, enabled=True)
        assert sensor._ocr_enabled is False


# ── Sistema ──────────────────────────────────────────────────

class TestSystemSensor:
    def test_no_source_offline(self, bus, monkeypatch):
        monkeypatch.setattr("core.perception.system_sensor.HAS_PSUTIL", False)
        sensor = SystemSensor(event_bus=bus, enabled=True, analyzer=None)
        assert not sensor.available
        assert sensor.run_once() == []

    def test_baseline_first_read(self, bus):
        sensor = SystemSensor(event_bus=bus, enabled=True, analyzer=object(),
                              cpu_delta=15.0)
        sensor._read = lambda: {"cpu": 10.0, "ram": 30.0, "disk": 50.0}
        assert sensor.sense() == []

    def test_delta_jump_emits(self, bus):
        sensor = SystemSensor(event_bus=bus, enabled=True, analyzer=object(),
                              cpu_delta=15.0, ram_delta=10.0, disk_delta=10.0)
        sensor._read = lambda: {"cpu": 10.0, "ram": 30.0, "disk": 50.0}
        sensor.sense()  # baseline
        sensor._read = lambda: {"cpu": 10.0, "ram": 45.0, "disk": 50.0}
        events = sensor.sense()
        assert any(e.event_type == EVENT_SYSTEM_METRIC and e.payload["metric"] == "ram"
                   for e in events)

    def test_critical_cpu_alert_once(self, bus):
        sensor = SystemSensor(event_bus=bus, enabled=True, analyzer=object(),
                              cpu_delta=15.0, cpu_critical=90.0)
        sensor._read = lambda: {"cpu": 50.0}
        sensor.sense()  # baseline
        sensor._read = lambda: {"cpu": 95.0}
        events = sensor.sense()
        assert any(e.event_type == EVENT_SYSTEM_ALERT for e in events)
        sensor._read = lambda: {"cpu": 96.0}
        assert all(e.event_type != EVENT_SYSTEM_ALERT for e in sensor.sense())


# ── Arquivos ─────────────────────────────────────────────────

class TestFilesystemSensor:
    def test_no_watch_dirs_offline(self, bus):
        sensor = FilesystemSensor(event_bus=bus, enabled=True, watch_dirs=())
        assert not sensor.available
        assert sensor.run_once() == []

    def test_create_and_remove(self, bus, tmp_path):
        sensor = FilesystemSensor(event_bus=bus, enabled=True,
                                  watch_dirs=(str(tmp_path),), debounce=0.0)
        assert sensor.run_once() == []  # linha de base
        target = tmp_path / "novo.txt"
        target.write_text("dados")
        events = sensor.sense()
        assert len(events) == 1
        assert events[0].event_type == EVENT_FILESYSTEM
        assert events[0].payload["action"] == "created"
        target.unlink()
        events = sensor.sense()
        assert events and events[0].payload["action"] == "removed"

    def test_debounce(self, bus, tmp_path):
        import os
        import time

        sensor = FilesystemSensor(event_bus=bus, enabled=True,
                                  watch_dirs=(str(tmp_path),), debounce=60.0)
        sensor.run_once()
        target = tmp_path / "a.txt"
        target.write_text("x")
        base = time.time()
        os.utime(target, (base, base))
        assert len(sensor.sense()) == 1  # criado

        target.write_text("y")
        os.utime(target, (base + 1, base + 1))
        assert len(sensor.sense()) == 1  # modificado (ação distinta)

        target.write_text("z")
        os.utime(target, (base + 2, base + 2))
        assert sensor.sense() == []  # 2ª modificação suprimida pelo debounce


# ── Rede ─────────────────────────────────────────────────────

class TestNetworkSensor:
    def test_transition_emits(self, bus, monkeypatch):
        sensor = NetworkSensor(event_bus=bus, enabled=True)
        monkeypatch.setattr(sensor, "_probe", lambda: True)
        assert sensor.sense() == []  # baseline online
        monkeypatch.setattr(sensor, "_probe", lambda: False)
        events = sensor.sense()
        assert len(events) == 1 and events[0].payload["state"] == "down"
        monkeypatch.setattr(sensor, "_probe", lambda: True)
        events = sensor.sense()
        assert events and events[0].payload["state"] == "up"

    def test_no_noise_when_stable(self, bus, monkeypatch):
        sensor = NetworkSensor(event_bus=bus, enabled=True)
        monkeypatch.setattr(sensor, "_probe", lambda: True)
        sensor.sense()
        assert sensor.sense() == []


# ── Hardware ESP32 ───────────────────────────────────────────

class TestHardwareSensor:
    def test_without_hardware_offline(self, bus):
        sensor = HardwareSensor(event_bus=bus, enabled=True, hardware=None)
        assert not sensor.available
        assert sensor.run_once() == []

    def test_connect_transition(self, bus):
        class FakeHW:
            connected = False
            available = True

        hw = FakeHW()
        sensor = HardwareSensor(event_bus=bus, enabled=True, hardware=hw)
        assert sensor.run_once() == []  # baseline
        hw.connected = True
        events = sensor.sense()
        assert events and events[0].event_type == EVENT_HARDWARE
        assert events[0].payload["state"] == "connected"


# ── Ponte de atenção ─────────────────────────────────────────

class TestAttentionBridge:
    def test_high_event_reaches_state_and_memory(self, bus, attention, state, memory, logger):
        AttentionBridge(bus, attention, state, memory, logger)
        bus.publish(Event(event_type=EVENT_CAMERA, source="camera",
                          payload={"text": "Movimento detectado"},
                          priority=PRIORITY_HIGH, confidence=0.7))
        assert state.perception.last_attention in ("HIGH", "NORMAL")
        assert state.event_history
        assert memory.episodic.total() == 1

    def test_low_event_only_logged(self, bus, attention, state, memory, logger):
        AttentionBridge(bus, attention, state, memory, logger)
        bus.publish(Event(event_type=EVENT_SCREEN_CHANGED, source="screen",
                          payload={"text": "Janela ativa"},
                          priority=PRIORITY_LOW, confidence=0.5))
        assert state.event_history == []  # não chamou atenção o suficiente
        assert memory.episodic.total() == 0
        assert attention.recent_attention()

    def test_user_message_not_duplicated_in_state(self, bus, attention, state, logger):
        AttentionBridge(bus, attention, state, logger)
        bus.publish(Event(event_type=EVENT_USER_MESSAGE, source="neural",
                          payload={"text": "qual uso da cpu"},
                          priority=80, confidence=1.0))
        assert state.event_history == []  # registrado apenas no log

    def test_disabled_bridge_ignores(self, bus, attention, state, logger):
        bridge = AttentionBridge(bus, attention, state, logger)
        bridge.set_enabled(False)
        bus.publish(Event(event_type=EVENT_NETWORK, source="network",
                          payload={"text": "internet perdida"},
                          priority=PRIORITY_HIGH))
        assert bus.get_stats()["published"] == 1
        assert attention.recent_attention() == []


# ── Perception Manager ───────────────────────────────────────

class TestPerceptionManager:
    def test_start_stop_no_errors(self, bus, attention, state, logger):
        cfg = PerceptionConfig().update_env(
            enabled=True, network_enabled=False, system_enabled=False,
            screen_enabled=False, camera_enabled=False, mic_enabled=False,
        )
        manager = PerceptionManager.with_defaults(
            event_bus=bus, state=state, attention=attention,
            config=cfg, logger=logger,
        )
        manager.start()
        assert manager.is_enabled
        assert state.perception.enabled is True
        assert len(manager.sensors) == 7
        manager.stop()
        assert not manager.is_enabled
        assert state.perception.enabled is False

    def test_no_fake_events_when_unavailable(self, bus, attention, state, logger):
        cfg = PerceptionConfig().update_env(
            enabled=True, camera_enabled=False, mic_enabled=False,
            screen_enabled=False, network_enabled=False, system_enabled=False,
            hardware_enabled=True, filesystem_watch_dirs=(),
        )
        before = bus.get_stats()["published"]
        manager = PerceptionManager.with_defaults(
            event_bus=bus, state=state, attention=attention,
            config=cfg, logger=logger,
        )
        for sensor in manager.sensors.values():
            sensor.run_once()
        assert bus.get_stats()["published"] == before  # nenhum evento falso

    def test_toggle_perception(self, bus, attention, state, logger):
        cfg = PerceptionConfig().update_env(
            enabled=True, network_enabled=False, system_enabled=False,
            screen_enabled=False,
        )
        manager = PerceptionManager.with_defaults(
            event_bus=bus, state=state, attention=attention, config=cfg, logger=logger,
        )
        manager.start()
        assert manager.toggle_perception(False) is False
        assert manager.toggle_perception(True) is True

    def test_set_sensor_enabled(self, bus):
        sensor = DummySensor(enabled=True)
        manager = PerceptionManager(event_bus=bus, sensors={"dummy": sensor})
        assert manager.set_sensor_enabled("dummy", False)
        assert not sensor.enabled
        assert not manager.set_sensor_enabled("nao_existe", False)

    def test_format_helpers(self, bus, attention, state, logger):
        cfg = PerceptionConfig().update_env(
            enabled=True, network_enabled=False, system_enabled=False,
            screen_enabled=False,
        )
        manager = PerceptionManager.with_defaults(
            event_bus=bus, state=state, attention=attention, config=cfg, logger=logger,
        )
        manager.start()
        assert "Câmera" in manager.format_sensors()
        assert manager.format_attention()  # não explode
        assert "Câmera" in manager.format_camera()
        manager.stop()
        assert "desativada" in manager.describe()


# ── Integração: handlers e rota determinística ───────────────

class TestPerceptionIntent:
    def test_handler_registered(self):
        import core.handlers  # noqa: F401  (registra os handlers)
        from core.commands import registry

        assert registry.has_intent("perception")

    def test_handler_status(self, monkeypatch, capfd):
        import core.handlers  # noqa: F401
        from core.handlers import handle_perception

        class FakeManager:
            def describe(self):
                return "Percepção ativa com 2 sensores."
            def format_sensors(self):
                return "  • Câmera: desativado\n  • Sistema: ativo"
            def format_attention(self):
                return "  • [HIGH] movimento"
            def format_camera(self):
                return "Câmera indisponível."
            def toggle_perception(self, *_a, **_k):
                return False

        out = handle_perception("status", {}, perception=FakeManager())
        assert "Percepção ativa" in out

    def test_toggle_off(self):
        import core.handlers  # noqa: F401
        from core.handlers import handle_perception

        toggled = []
        class FakeManager:
            def toggle_perception(self, on=None):
                toggled.append(on)
                return bool(on)

        handle_perception("toggle", {"target": "off"}, perception=FakeManager())
        assert toggled[-1] is False

    def test_deterministic_routing_status(self):
        from core.neural.reasoning.reasoning_router import DeterministicEngine

        engine = DeterministicEngine()
        intents = engine.parse("o que você está percebendo?")
        assert intents and intents[0].module == "perception"
        assert intents[0].action == "status"

    def test_deterministic_routing_sensors(self):
        from core.neural.reasoning.reasoning_router import DeterministicEngine

        intents = DeterministicEngine().parse("quais sensores estão ativos?")
        assert intents and intents[0].module == "perception"
        assert intents[0].action == "sensors"

    def test_deterministic_routing_attention(self):
        from core.neural.reasoning.reasoning_router import DeterministicEngine

        intents = DeterministicEngine().parse("o que chamou sua atenção?")
        assert intents and intents[0].module == "perception"
        assert intents[0].action == "attention"

    def test_deterministic_routing_camera(self):
        from core.neural.reasoning.reasoning_router import DeterministicEngine

        intents = DeterministicEngine().parse("a câmera está disponível?")
        assert intents and intents[0].module == "perception"
        assert intents[0].action == "camera"

    def test_deterministic_routing_toggle_off(self):
        from core.neural.reasoning.reasoning_router import DeterministicEngine

        intents = DeterministicEngine().parse("desative a percepção")
        assert intents and intents[0].module == "perception"
        assert intents[0].params["target"] == "off"

    def test_deterministic_routing_toggle_on(self):
        from core.neural.reasoning.reasoning_router import DeterministicEngine

        intents = DeterministicEngine().parse("ative a percepção")
        assert intents and intents[0].params["target"] == "on"


def test_config_env_defaults(monkeypatch):
    for key in ("ARIS_CAMERA_ENABLED", "ARIS_MIC_ENABLED", "ARIS_SCREEN_OCR_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    cfg = PerceptionConfig.load()
    assert cfg.camera_enabled is False   # câmera não exigida por padrão
    assert cfg.mic_enabled is False
    assert cfg.screen_ocr_enabled is False  # OCR pesado desligado por padrão
    assert cfg.enabled is True
