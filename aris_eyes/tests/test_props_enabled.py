"""Kill-switch props_enabled: com False, os olhos funcionam como antes (sem enfeites/cenas).

Cenarios:
    - config: padrao True e roundtrip save/load em JSON;
    - widget: props_enabled False, frame de props nunca montado;
    - API: scene/prop/music/accent retornam erro; mood continua ok.
"""
import pytest

pytest.importorskip("PySide6")

from aris_eyes.api import EyesAPI
from aris_eyes.config import Config
from aris_eyes.eyes.presets import Mood
from aris_eyes.modes import DisplayController
from aris_eyes.ui.window import EyesWindow
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _stack(tmp_path, enabled):
    cfg = Config.load(tmp_path / "c.json")
    cfg.props_enabled = enabled
    window = EyesWindow(cfg)
    controller = DisplayController(window)
    api = EyesAPI(window.eyes, controller, cfg, quit_callback=lambda: None)
    return window, api


def test_config_padrao_liga_e_roundtrip_json(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    assert cfg.props_enabled is True
    cfg.props_enabled = False
    cfg.save()
    assert Config.load(tmp_path / "c.json").props_enabled is False


def test_desligado_props_dao_erro_e_mood_continua_ok(app, tmp_path):
    window, api = _stack(tmp_path, enabled=False)
    try:
        assert window.eyes.props_enabled is False
        assert window.eyes._pframe is None          # frame de props nunca montado
        assert api.execute("scene spotify").startswith("erro")
        assert api.execute("scene off").startswith("erro")
        assert api.execute("prop hearts on").startswith("erro")
        assert api.execute("music 0.5").startswith("erro")
        assert api.execute("accent #ff0000").startswith("erro")
        # olhos continuam funcionando como antes
        assert api.execute("mood happy") == "ok"
        assert window.eyes.current_mood() is Mood.HAPPY
        assert "scene=-" in api.execute("status") and "props=-" in api.execute("status")
    finally:
        window.eyes.stop()
        window.hide()


def test_ligado_props_funcionam(app, tmp_path):
    window, api = _stack(tmp_path, enabled=True)
    try:
        assert window.eyes.props_enabled is True
        assert api.execute("scene spotify") == "ok"
        assert window.eyes.current_mood() is Mood.MUSIC
        assert api.execute("scene off") == "ok"
    finally:
        window.eyes.stop()
        window.hide()
