"""Integracao dos novos humores/props/cenas com a janela e a API de comandos (Qt offscreen)."""
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from aris_eyes.api import EyesAPI
from aris_eyes.config import Config
from aris_eyes.eyes.presets import Mood
from aris_eyes.modes import DisplayController
from aris_eyes.ui.window import EyesWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def stack(app, tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    window = EyesWindow(cfg)
    controller = DisplayController(window)
    api = EyesAPI(window.eyes, controller, cfg, quit_callback=lambda: None)
    yield window, api
    window.eyes.stop()
    window.hide()


def pump(app, seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


def test_cena_spotify_pela_api(app, stack):
    window, api = stack
    assert api.execute("scene spotify") == "ok"
    assert window.eyes.current_mood() is Mood.MUSIC
    status = api.execute("status")
    assert "scene=spotify" in status and "notes" in status and "equalizer" in status
    assert api.execute("scene off") == "ok"
    assert "scene=-" in api.execute("status")


def test_cena_com_tempo_e_desconhecida(app, stack):
    window, api = stack
    assert api.execute("scene apaixonado 1").startswith("ok")
    assert api.execute("scene xpto").startswith("erro")
    assert api.execute("scene").startswith("erro")
    assert api.execute("scene apaixonado abc").startswith("erro")


def test_prop_manual_e_erros(app, stack):
    window, api = stack
    assert api.execute("prop hearts on") == "ok"
    assert "hearts" in api.execute("status")
    assert api.execute("prop hearts off") == "ok"
    assert api.execute("prop hearts on 0.5") == "ok"
    assert api.execute("prop nada on").startswith("erro")
    assert api.execute("prop hearts talvez").startswith("erro")
    assert api.execute("prop hearts on xx").startswith("erro")


def test_music_e_accent(app, stack):
    window, api = stack
    assert api.execute("music 0.8") == "ok"
    assert api.execute("music off") == "ok"
    assert api.execute("music abc").startswith("erro")
    assert api.execute("accent #ff8800") == "ok"
    assert window.eyes.scenes.accent == "#ff8800"
    assert api.execute("accent 00ff00") == "ok"
    assert window.eyes.scenes.accent == "#00ff00"
    assert api.execute("accent azul").startswith("erro")
    assert api.execute("accent off") == "ok"
    assert window.eyes.scenes.accent is None


def test_mood_novo_pela_api_liga_props_e_mood_comum_desliga(app, stack):
    window, api = stack
    assert api.execute("mood apaixonado") == "ok"
    assert window.eyes.current_mood() is Mood.LOVE
    assert window.eyes.props.active_names() == {"eye_heart", "hearts"}
    assert api.execute("thinking") == "ok"
    assert window.eyes.props.active_names() == set()


def test_mudar_humor_encerra_a_cena(app, stack):
    window, api = stack
    api.execute("scene fone")
    api.execute("mood speaking")              # a ARIS comecou a falar
    assert window.eyes.scenes.current is None
    assert window.eyes.props.active_names() == set()


def test_janela_pinta_props_sem_erro(app, stack, tmp_path):
    window, api = stack
    window.resize(600, 340)
    window.show()
    window.eyes.start(30)
    api.execute("scene spotify")
    pump(app, 0.6)
    image = window.eyes.grab().toImage()
    assert image.width() > 0
    colors = {image.pixelColor(x, y).rgb() for x in range(0, image.width(), 7) for y in range(0, image.height(), 7)}
    assert len(colors) > 10
    image.save(str(tmp_path / "janela_spotify.png"))
