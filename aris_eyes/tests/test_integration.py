"""Testes com Qt de verdade (plataforma offscreen): janela, API de comandos e socket de controle."""
import threading
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from aris_eyes.api import EyesAPI
from aris_eyes.client import send
from aris_eyes.config import Config
from aris_eyes.control import ControlServer
from aris_eyes.eyes.presets import Mood
from aris_eyes.modes import DisplayController, Mode
from aris_eyes.ui.window import EyesWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def stack(app, tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    window = EyesWindow(cfg)
    controller = DisplayController(window)
    quit_flag = []
    api = EyesAPI(window.eyes, controller, cfg, quit_callback=lambda: quit_flag.append(1))
    yield window, controller, api, quit_flag
    window.eyes.stop()
    window.hide()


def pump(app, seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def test_janela_percorre_os_tres_modos(app, stack):
    window, controller, api, _ = stack
    controller.set_mode(Mode.FULLSCREEN)
    pump(app)
    assert window.isVisible() and window.shown_mode == "fullscreen" and window.eyes.is_running()
    controller.set_mode(Mode.MINI)
    pump(app)
    assert window.isVisible() and window.shown_mode == "mini" and window.eyes.mini_style
    assert (window.width(), window.height()) == (300, 170)
    controller.set_mode(Mode.HIDDEN)
    pump(app)
    assert not window.isVisible() and not window.eyes.is_running()      # escondida nao gasta CPU
    controller.show()
    pump(app)
    assert window.isVisible() and window.shown_mode == "mini"           # voltou ao ultimo modo visivel


def test_comandos_da_api(app, stack):
    window, controller, api, quit_flag = stack
    assert api.execute("ping") == "pong"
    assert api.execute("mini") == "ok" and controller.mode is Mode.MINI
    assert api.execute("toggle") == "ok" and controller.mode is Mode.FULLSCREEN
    assert api.execute("hide") == "ok" and controller.mode is Mode.HIDDEN
    assert api.execute("show") == "ok" and controller.mode is Mode.FULLSCREEN
    assert api.execute("mood pensando") == "ok" and window.eyes.current_mood() is Mood.THINKING
    assert api.execute("state falando") == "ok" and window.eyes.current_mood() is Mood.SPEAKING
    assert api.execute("happy") == "ok" and window.eyes.current_mood() is Mood.HAPPY
    assert api.execute("look 0.5 -0.2 2") == "ok" and api.execute("look center") == "ok"
    assert api.execute("speech 0.7") == "ok" and api.execute("speech off") == "ok"
    assert api.execute("blink") == "ok"
    assert api.execute("top off") == "ok" and window.cfg.always_on_top is False
    assert api.execute("status").startswith("mode=fullscreen mood=happy")
    assert api.execute("quit") == "ok" and quit_flag == [1]


def test_comandos_invalidos_dao_erro_sem_quebrar(app, stack):
    _, controller, api, _ = stack
    for bad in ("", "mood", "mood xyz", "look a b", "look 1", "speech abc", "top talvez", "rm -rf /", "mode xx"):
        assert api.execute(bad).startswith("erro"), bad


def test_socket_de_controle_de_ponta_a_ponta(app, stack, tmp_path):
    window, controller, api, _ = stack
    path = str(tmp_path / "eyes.sock")
    server = ControlServer(api.execute, path)
    assert server.start()
    results = {}

    def client():
        results["ping"] = send("ping", path=path)
        results["mood"] = send("mood thinking", path=path)
        results["mini"] = send("mini", path=path)
        results["bad"] = send("comando-que-nao-existe", path=path)
        results["long"] = send("x" * 5000, path=path)

    thread = threading.Thread(target=client)
    thread.start()
    while thread.is_alive():
        app.processEvents()
        time.sleep(0.005)
    server.stop()
    assert results["ping"] == "pong" and results["mood"] == "ok" and results["mini"] == "ok"
    assert results["bad"].startswith("erro") and results["long"].startswith("erro")
    assert window.eyes.current_mood() is Mood.THINKING and controller.mode is Mode.MINI


def test_cliente_sem_servidor_devolve_none(tmp_path):
    assert send("ping", path=str(tmp_path / "nao-existe.sock")) is None


def test_renderiza_cada_expressao_com_olhos_azuis(app, stack):
    from PySide6.QtGui import QColor
    window, controller, api, _ = stack
    window.resize(640, 360)
    for mood in Mood:
        window.eyes.set_mood(mood)
        for _ in range(120):
            window.eyes._frame = window.eyes.animator.update(1 / 60)
        image = window.eyes.grab().toImage()
        blue = sum(1 for x in range(0, image.width(), 4) for y in range(0, image.height(), 4)
                   if (c := QColor(image.pixel(x, y))).blue() > 150 and c.blue() > c.red() + 40)
        assert blue > 20, f"{mood}: nao desenhou olhos azuis"
