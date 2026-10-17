"""Botões do HUD + voz sempre pt-BR (sem inglês no fallback)."""

import pytest

pygame = pytest.importorskip("pygame")

from core.vision.hud import hud_pygame as hud
from utils import voice_hybrid as vh


class _FakeVoice:
    def __init__(self, vid, name):
        self.id = vid
        self.name = name


class _FakeEngine:
    def __init__(self):
        self.props = {}
        self.said = []
        self.voices = [
            _FakeVoice("english-id", "Microsoft David English"),
            _FakeVoice("pt-id", "Microsoft Maria pt-BR"),
        ]

    def getProperty(self, name):
        return self.voices if name == "voices" else None

    def setProperty(self, name, value):
        self.props[name] = value

    def say(self, text):
        self.said.append(text)

    def runAndWait(self):
        pass


def test_pyttsx3_fallback_selects_pt_voice(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(vh, "_PYTTSX3_AVAILABLE", True)
    monkeypatch.setattr(vh.pyttsx3, "init", lambda: engine)
    vh.HybridVoice._speak_pyttsx3_ptbr("olá mundo")
    assert engine.props.get("voice") == "pt-id"
    assert engine.said == ["olá mundo"]


def test_pyttsx3_fallback_no_engine_no_crash(monkeypatch):
    monkeypatch.setattr(vh, "_PYTTSX3_AVAILABLE", False)
    vh.HybridVoice._speak_pyttsx3_ptbr("olá")  # não levanta


def test_pyttsx3_fallback_never_speaks_english(monkeypatch):
    """Sem voz pt-BR instalada, o fallback fica calado (nada de inglês)."""
    engine = _FakeEngine()
    engine.voices = [_FakeVoice("english-id", "Microsoft Zira Desktop - English (United States)")]
    monkeypatch.setattr(vh, "_PYTTSX3_AVAILABLE", True)
    monkeypatch.setattr(vh.pyttsx3, "init", lambda: engine)
    vh.HybridVoice._speak_pyttsx3_ptbr("olá mundo")
    assert engine.said == []
    assert "voice" not in engine.props


def test_all_instances_share_single_speech_lock():
    """ARIS e HUD não podem falar ao mesmo tempo (uma fala por vez)."""
    first = vh.HybridVoice(auto_select_mic=False)
    second = vh.HybridVoice(auto_select_mic=False)
    assert first._lock is second._lock
    assert first._lock is vh._SPEECH_LOCK


def test_default_tts_voice_is_feminine():
    import inspect
    src = inspect.getsource(vh.HybridVoice._edge_tts_speak)
    assert "pt-BR-FranciscaNeural" in src
    assert "AntonioNeural" not in src


def test_aris_status_not_added_to_chat():
    panel = hud.ChatPanel()
    panel._handle_event({"type": "aris_status", "payload": {"state": "thinking"}})
    assert panel.messages == []
    assert panel.last_status == "thinking"


def test_chat_message_still_added():
    panel = hud.ChatPanel()
    panel._handle_event({"type": "chat_message",
                         "payload": {"sender": "ARIS", "text": "oi"}})
    assert len(panel.messages) == 1
    assert panel.messages[0][0] == "ARIS"
