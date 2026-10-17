"""Semântica de gesto barehands: pinça relativa + release por velocidade.

Cobre a camada de interpretação (workspace.py — razão gap/tamanho-mão,
release bar speed-aware, histórico pré-release) e o mapeamento das ações
do HUD (arrastar/flick/place/tap/zoom) alimentado por landmarks sintéticos.
"""

import pytest

from core.vision.hud.barehands import release_bar
from core.vision.hud.workspace import (
    PINCH_ENTER,
    PINCH_EXIT,
    RATIO_ENTER,
    RATIO_ENTER_SIDE,
    RATIO_RELEASE,
    RATIO_RELEASE_FAST,
    SPEED_FAST,
    HandPinch,
    WorkspaceItem,
    hand_aspect,
    pinch_ratio,
    ratio_enter_ceiling,
)

hp = pytest.importorskip("core.vision.hud.hud_pygame")

# Landmark sintético de 21 pontos (pulso 0, MCPs 5/17, pontas 4/8)
_BASE = [
    (0.50, 1.00),  # 0 pulso
    (0.40, 0.92), (0.33, 0.85), (0.25, 0.74), (0.18, 0.62),  # 1-4 polegar
    (0.44, 0.55), (0.45, 0.42), (0.46, 0.29), (0.46, 0.18),  # 5-8 indicador
    (0.52, 0.54), (0.52, 0.40), (0.52, 0.32), (0.52, 0.24),  # 9-12 médio
    (0.60, 0.56), (0.61, 0.43), (0.61, 0.35), (0.61, 0.28),  # 13-16 anelar
    (0.67, 0.60), (0.69, 0.49), (0.70, 0.42), (0.70, 0.36),  # 17-20 mindinho
]


def _hand(pinched: bool = False, wide: bool = False, pointing: bool = False):
    pts = [list(p) for p in _BASE]
    if pinched:
        pts[6] = [0.45, 0.46]
        pts[7] = [0.44, 0.45]
        pts[8] = [0.43, 0.45]
        pts[4] = [0.41, 0.44]
    elif wide:
        pts[4] = [0.12, 0.68]
        pts[8] = [0.50, 0.12]
    if pointing:
        pts[0] = [0.555, 0.675]
    return [(x, y) for x, y in pts]


def _shift(hand, dx: float, dy: float = 0.0):
    return [(x + dx, y + dy) for x, y in hand]


def test_pinch_ratio_near_far_and_scale_invariant():
    near = pinch_ratio(_hand(pinched=True))
    far = pinch_ratio(_hand())
    wide = pinch_ratio(_hand(wide=True))
    assert near < 0.05
    assert far > 0.55
    assert wide > RATIO_RELEASE_FAST
    assert near < RATIO_ENTER < far
    # invariante de escala/tradução: longe da câmera o limiar é o mesmo
    moved = [(x * 3.0 + 0.7, y * 3.0 - 0.2) for x, y in _hand(pinched=True)]
    assert pinch_ratio(moved) == pytest.approx(near)


def test_hand_aspect_regimes():
    front = hand_aspect(_hand())
    assert front > 2.0
    assert ratio_enter_ceiling(front) == RATIO_ENTER
    side = hand_aspect(_hand(pointing=True))
    assert side < 2.0
    assert ratio_enter_ceiling(side) == RATIO_ENTER_SIDE
    assert RATIO_ENTER < RATIO_ENTER_SIDE


def test_ratio_constants_match_barehands_release_bar():
    assert RATIO_RELEASE == release_bar(0.0) == 0.55
    assert RATIO_RELEASE_FAST == release_bar(1200.0) == 0.70
    assert release_bar(SPEED_FAST) == 0.55
    assert release_bar(SPEED_FAST + 1.0) == 0.70


def test_legacy_handpinch_defaults_unchanged():
    p = HandPinch()
    assert (p.enter, p.exit, p.speed_aware) == (PINCH_ENTER, PINCH_EXIT, False)
    assert p.update(0.10, 0, 0, 0.0) is False
    assert p.update(0.04, 0, 0, 0.1) is True   # entra < 0.05
    assert p.update(0.06, 0, 0, 0.2) is True   # segura até 0.07
    assert p.update(0.08, 0, 0, 0.3) is False  # solta > 0.07


def test_speed_aware_enter_ceiling_by_aspect():
    front = hand_aspect(_hand())
    side = hand_aspect(_hand(pointing=True))
    p = HandPinch(speed_aware=True)
    assert (p.enter, p.exit) == (RATIO_ENTER, RATIO_RELEASE)
    assert p.update(0.34, 100.0, 100.0, 10.0, front) is False  # > ceiling 0.32
    p_side = HandPinch(speed_aware=True)
    assert p_side.update(0.34, 100.0, 100.0, 10.0, side) is True  # < ceiling 0.38
    assert p.update(0.20, 100.0, 100.0, 10.1, front) is True


def test_speed_aware_slow_release_at_55():
    p = HandPinch(speed_aware=True)
    p.update(0.20, 0.0, 0.0, 20.0)
    assert p.update(0.54, 0.0, 0.0, 20.05) is True   # 0.54 < 0.55 segura
    assert p.update(0.60, 0.0, 0.0, 20.10) is False  # >= 0.55 solta (lento)
    assert p.last_speed == 0.0


def test_speed_aware_fast_hold_and_two_frame_release():
    p = HandPinch(speed_aware=True)
    t = 30.0
    p.update(pinch_ratio(_hand(pinched=True)), 0.0, 0.0, t)
    for i in range(1, 6):  # 60px/10ms = 6000 px/s (rápido de verdade)
        t += 0.010
        p.update(pinch_ratio(_hand(pinched=True)), 60.0 * i, 0.0, t)
    assert p.pinched is True
    assert p.last_speed == pytest.approx(6000.0, rel=0.01)
    # aberto 0.60 (>= 0.55) mas rápido -> barra 0.70 segura a pinça
    t += 0.010
    assert p.update(0.60, 360.0, 0.0, t) is True
    # solta só no segundo quadro aberto (open_prev)
    t += 0.010
    assert p.update(pinch_ratio(_hand(wide=True)), 420.0, 0.0, t) is True
    t += 0.010
    assert p.update(pinch_ratio(_hand(wide=True)), 480.0, 0.0, t) is False
    assert p.pinched is False


def test_pre_release_speed_uses_only_last_200ms():
    p = HandPinch()
    now = 50.0
    for i in range(21):  # 50px a cada 50ms = 1000 px/s
        p.update(0.10, 50.0 * i, 0.0, now)
        now += 0.05
    assert p.last_speed == pytest.approx(1000.0, rel=0.01)
    assert p.pre_release_speed(now) == pytest.approx(1000.0, rel=0.01)


def test_reset_zeroes_pinch_and_speed():
    p = HandPinch(speed_aware=True)
    t = 70.0
    p.update(0.20, 0.0, 0.0, t)
    for i in range(1, 6):
        t += 0.010
        p.update(0.20, 60.0 * i, 0.0, t)
    assert p.pinched is True
    assert p.last_speed > SPEED_FAST
    p.reset()
    assert p.pinched is False
    assert p.last_speed == 0.0
    assert p.pre_release_speed(t + 1.0) == 0.0


class _Clock:
    """Relógio falso para injetar o tempo de _process_hands sem dormir."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return self.t

    def strftime(self, fmt: str) -> str:
        import time as _realt
        return _realt.strftime(fmt)

    def sleep(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture()
def hud(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(hp, "time", clock)
    try:
        h = hp.HUD()
    except Exception as exc:  # pragma: no cover - depende do display
        pytest.skip(f"HUD indisponível sem display: {exc}")
    return h, clock


def test_hud_open_hand_triggers_nothing(hud):
    h, _clock = hud
    h._process_hands([_hand()])
    assert h._pinch[0].pinched is False
    assert all(v == 0 for v in h.gesture_stats.values())


def test_hud_pinch_drags_then_places_slowly(hud):
    h, clock = hud
    h._process_hands([_hand(pinched=True)])
    assert h._pinch[0].pinched is True
    x0 = h.hologram.target_x
    for i in range(1, 6):
        clock.t += 0.03
        h._process_hands([_shift(_hand(pinched=True), -0.03 * i)])
    assert h.gesture_stats["drag"] > 0
    assert h.hologram.target_x != x0
    # segura parado >0.35s (não é tap) e solta devagar -> place
    for _ in range(8):
        clock.t += 0.05
        h._process_hands([_shift(_hand(pinched=True), -0.15)])
    clock.t += 0.05
    h._process_hands([_shift(_hand(), -0.15)])
    assert h.gesture_stats["place"] == 1
    assert h.gesture_stats["flick"] == 0
    assert h.gesture_stats["tap"] == 0
    assert h._pinch[0].pinched is False


def test_hud_fast_release_flicks(hud):
    h, clock = hud
    h._process_hands([_hand(pinched=True)])
    assert h._pinch[0].pinched is True
    # movimento sustentado por toda a janela de 200ms -> >800 px/s
    for i in range(1, 9):
        clock.t += 0.03
        h._process_hands([_shift(_hand(pinched=True), 0.06 * i)])
    assert h._pinch[0].last_speed > SPEED_FAST
    # solta aberto e rápido: primeiro quadro segura, segundo solta (flick)
    clock.t += 0.03
    h._process_hands([_shift(_hand(wide=True), 0.06 * 9)])
    assert h._pinch[0].pinched is True
    clock.t += 0.03
    h._process_hands([_shift(_hand(wide=True), 0.06 * 10)])
    assert h.gesture_stats["flick"] == 1
    assert h.gesture_stats["tap"] == 0
    assert h.gesture_stats["place"] == 0


def test_hud_quick_pinch_releases_as_tap(hud):
    h, clock = hud
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.10
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.05
    h._process_hands([_hand()])
    assert h.gesture_stats["tap"] == 1
    assert h.gesture_stats["flick"] == 0
    assert h.gesture_stats["place"] == 0


def test_hud_two_pinched_hands_zoom(hud):
    h, clock = hud
    h._process_hands([_shift(_hand(pinched=True), -0.10),
                      _shift(_hand(pinched=True), 0.10)])
    assert h._pinch[0].pinched and h._pinch[1].pinched
    base = h.hologram.target_scale
    for i in range(1, 6):
        clock.t += 0.04
        h._process_hands([_shift(_hand(pinched=True), -0.10 - 0.01 * i),
                          _shift(_hand(pinched=True), 0.10 + 0.01 * i)])
    assert h.gesture_stats["zoom"] > 0
    assert h.hologram.target_scale > base
    assert h.gesture_stats["flick"] == 0


def _fist():
    """Punho fechado: pontas coladas no palmo (lê como pinça, mas é punho)."""
    pts = [list(p) for p in _BASE]
    pts[8] = [0.46, 0.60]
    pts[12] = [0.52, 0.60]
    pts[16] = [0.61, 0.60]
    pts[20] = [0.70, 0.62]
    pts[4] = [0.44, 0.58]
    return [(x, y) for x, y in pts]


def test_hud_pinch_in_empty_space_does_not_drag_hologram(hud):
    """Bug: pinça longe do central puxava o holograma junto."""
    h, clock = hud
    far = _shift(_hand(pinched=True), 0.30)  # sx=345 dist~297 do central
    h._process_hands([far])
    assert h._pinch[0].pinched is True
    assert h.dragging is None and h._ws_grab is None
    x0, y0 = h.hologram.target_x, h.hologram.target_y
    for i in range(1, 4):
        clock.t += 0.04
        h._process_hands([_shift(far, 0.01 * i)])
    assert (h.hologram.target_x, h.hologram.target_y) == (x0, y0)
    assert h.gesture_stats["drag"] == 0


def test_hud_tap_on_hologram_opens_files_browser(hud, monkeypatch):
    """Bug: tap no central não abria o navegador ARQUIVOS."""
    h, clock = hud
    opened = []
    monkeypatch.setattr(h, "open_folder_gesture", lambda: opened.append(1))
    h._process_hands([_hand(pinched=True)])   # pinch perto do central
    assert h.dragging == "hand"
    clock.t += 0.10
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.05
    # Solta com a ponta em (640,400) = centro exato do holograma
    h._process_hands([_shift(_hand(), 0.04, 0.32)])
    assert opened == [1]
    assert h.gesture_stats["tap"] == 1
    assert h.gesture_stats["flick"] == 0
    assert h.dragging is None


def test_hud_tap_on_card_enters_folder(hud):
    """Bug: tap não abria a pasta (hit-test circular perdia o canto)."""
    h, clock = hud
    card = WorkspaceItem(id="docs/sub", name="sub", kind="folder",
                         x=729.6, y=360.0)
    h.workspace.items = [card]
    h._process_hands([_hand(pinched=True)])   # mesmo ponto do card
    assert h._ws_grab is card
    clock.t += 0.15
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.05
    # Solta com a ponta ainda em cima do card = tap
    h._process_hands([_shift(_hand(), -0.03, 0.27)])
    assert h.gesture_stats["tap"] == 1
    # enter() falhou (docs/sub não existe no jail real) e caiu no expand
    assert card.open is True


def test_hud_flick_throws_card_without_teleport(hud):
    """Bug: flick teleportava o card 8x pra fora e ele sumia como fantasma."""
    h, clock = hud
    card = WorkspaceItem(id="docs/a.txt", name="a.txt", kind="file",
                         x=729.6, y=360.0)
    h.workspace.items = [card]
    h._process_hands([_hand(pinched=True)])
    assert h._ws_grab is card
    for i in range(1, 9):  # 38px/quadro = 1280 px/s e a mão não sai da tela
        clock.t += 0.03
        h._process_hands([_shift(_hand(pinched=True), 0.03 * i)])
    assert h._pinch[0].last_speed > SPEED_FAST
    clock.t += 0.03
    h._process_hands([_shift(_hand(wide=True), 0.03 * 9)])
    x_before, y_before = card.x, card.y
    clock.t += 0.03
    h._process_hands([_shift(_hand(wide=True), 0.03 * 10)])
    assert h.gesture_stats["flick"] == 1
    assert (card.x, card.y) == (x_before, y_before)  # não teletransporta
    assert abs(card.vx) > 0.0 or abs(card.vy) > 0.0  # voa com física
    # Fora da tela, some da vista sem tocar no arquivo
    card.x = 5000.0
    assert h.workspace.step(0.03, hp.WIDTH, hp.HEIGHT, None) == [card]
    assert card not in h.workspace.items


def test_hud_zoom_deadband_ignores_jitter(hud):
    """Bug: jitter de 1px já disparava zoom/giro com 2 mãos."""
    h, clock = hud
    left = _shift(_hand(pinched=True), -0.10)
    right = _shift(_hand(pinched=True), 0.10)
    h._process_hands([left, right])
    base = h.hologram.target_scale
    for i in range(1, 9):  # ±1px alternando por 0.32s
        clock.t += 0.04
        j = 0.0008 if i % 2 else -0.0008
        h._process_hands([_shift(left, j), _shift(right, -j)])
    assert h.gesture_stats["zoom"] == 0
    assert h.hologram.target_scale == base
    assert h.gesture_stats["flick"] == 0
    assert h.gesture_stats["reset"] == 0


def test_hud_two_fists_held_one_second_resets_hud(hud):
    """Reset: 2 punhos fechados por 1s fecha cards/config e centraliza."""
    h, clock = hud
    h.settings_open = True
    h.workspace.items = [WorkspaceItem(id="docs/a.txt", name="a.txt",
                                       kind="file", x=100.0, y=100.0)]
    h.hologram.x = h.hologram.target_x = 200.0
    h.hologram.scale = h.hologram.target_scale = 2.0
    hands = [_fist(), _shift(_fist(), 0.20)]
    h._process_hands(hands)
    assert h.gesture_stats["reset"] == 0
    assert h.gesture_stats["zoom"] == 0  # punho não vira zoom
    clock.t += 0.5
    h._process_hands(hands)
    assert h.gesture_stats["reset"] == 0
    clock.t += 0.6
    h._process_hands(hands)
    assert h.gesture_stats["reset"] == 1
    assert h.settings_open is False
    assert h.workspace.items == []
    assert h.hologram.target_x == hp.WIDTH / 2
    assert h.hologram.target_y == hp.HEIGHT / 2
    assert h.hologram.target_scale == 1.0
    # cooldown: continuar de punho não re-dispara na sequência
    clock.t += 1.2
    h._process_hands(hands)
    assert h.gesture_stats["reset"] == 1
