"""Testes da passada design: visualizer + gestos barehands.

Cobre:
- get_visualizer_config lista as 4 faces com Neural Core padrão
- /state (voice_state) reflete listening→thinking→speaking
- 3 gestos: pinch-enter (OK-sign), release speed-aware, peak-velocity throw
"""

from core.vision.hud.barehands import (
    contrast_ok,
    peak_velocity,
    pinch_enter,
    probation_kill,
    release_bar,
)
from core.vision.hud.server import HUDServer


def _server():
    return HUDServer(host="127.0.0.1", port=8798)


def test_visualizer_config_lists_four_faces_neural_default():
    srv = _server()
    cfg = srv.get_visualizer_config()
    assert cfg["face"] == "neural"
    ids = {f["id"] for f in cfg["faces"]}
    assert {"neural", "board", "radial", "rain"} <= ids


def test_voice_state_cycle_listening_thinking_speaking():
    srv = _server()
    for state in ("listening", "thinking", "speaking"):
        srv.publish_external("aris_status", {"state": state})
        got = srv.get_voice_state()
        assert got["state"] == state
    assert srv.get_voice_state()["loading"] is False  # speaking não carrega
    srv.publish_external("aris_status", {"state": "thinking"})
    assert srv.get_voice_state()["loading"] is True


def test_gesture_pinch_enter_ok_sign_vs_fist():
    # Gesto 1: pinça OK-sign entra; punho (back baixo) não entra
    assert pinch_enter(0.20, 1.5, ok_now=True, ok_ema=0.0) is True
    assert contrast_ok(back_mean=1.10, f8v=1.00, aspect=1.5, t_rel=0.5) is False
    assert contrast_ok(back_mean=1.60, f8v=1.00, aspect=1.5, t_rel=0.5) is True


def test_gesture_speed_aware_release():
    # Gesto 2: mão rápida exige abertura total; mão lenta libera cedo
    assert release_bar(1200.0) == 0.70
    assert release_bar(200.0) == 0.55
    assert probation_kill(4) is True
    assert probation_kill(3) is False


def test_gesture_peak_velocity_throw_direction():
    # Gesto 3: throw segue o pico de velocidade (direita)
    hist = [
        {"x": 0.0, "y": 0.0, "t": 0},
        {"x": 10.0, "y": 1.0, "t": 16},
        {"x": 60.0, "y": 2.0, "t": 32},
    ]
    vx, vy = peak_velocity(hist)
    assert vx > 0
    assert abs(vx) > abs(vy)
