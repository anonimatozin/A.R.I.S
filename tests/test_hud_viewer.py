"""Aba de documento do HUD: texto em 3D, modelo 3D e tap confiável.

Cobre o renderizador (warp em perspectiva, carregador .obj/.stl), o estado
da aba (scroll/rotação/zoom/hit) e os gestos no HUD — incluindo os casos de
tap que "só funcionavam às vezes": mão derivou, quadro perdido e mira lenta.
"""

import math

import pytest

pygame = pytest.importorskip("pygame")

from core.vision.hud import hud_pygame as hp  # noqa: E402
from core.vision.hud.model3d import (  # noqa: E402
    load_mesh,
    load_obj,
    load_stl,
    render_mesh,
)
from core.vision.hud.viewer import (  # noqa: E402
    PITCH_MAX,
    SCALE_MAX,
    SCALE_MIN,
    YAW_MAX,
    DocViewer,
    read_text_lines,
    warp_pitch,
    warp_yaw,
)
from core.vision.hud.workspace import (  # noqa: E402
    SPEED_FAST,
    TAP_MAX_DUR,
    TAP_MAX_MOVE,
    HandPinch,
    WorkspaceItem,
)

# ── Landmarks sintéticos (mesmo esqueleto dos testes de gesto) ──────────
_BASE = [
    (0.50, 1.00),
    (0.40, 0.92), (0.33, 0.85), (0.25, 0.74), (0.18, 0.62),
    (0.44, 0.55), (0.45, 0.42), (0.46, 0.29), (0.46, 0.18),
    (0.52, 0.54), (0.52, 0.40), (0.52, 0.32), (0.52, 0.24),
    (0.60, 0.56), (0.61, 0.43), (0.61, 0.35), (0.61, 0.28),
    (0.67, 0.60), (0.69, 0.49), (0.70, 0.42), (0.70, 0.36),
]

OBJ_CUBE = """v -1 -1 -1
v 1 -1 -1
v 1 1 -1
v -1 1 -1
v -1 -1 1
v 1 -1 1
v 1 1 1
v -1 1 1
f 1 2 3 4
f 5 8 7 6
f 1 5 6 2
f 2 6 7 3
f 3 7 8 4
f 5 1 4 8
"""

STL_TRI = """solid t
 facet normal 0 0 1
  outer loop
   vertex 0 0 0
   vertex 1 0 0
   vertex 0 1 0
  endloop
 endfacet
endsolid t
"""


def _hand(pinched: bool = False):
    pts = [list(p) for p in _BASE]
    if pinched:
        pts[6] = [0.45, 0.46]
        pts[7] = [0.44, 0.45]
        pts[8] = [0.43, 0.45]
        pts[4] = [0.41, 0.44]
    return [(x, y) for x, y in pts]


def _shift(hand, dx: float, dy: float = 0.0):
    return [(x + dx, y + dy) for x, y in hand]


def _at(hand, tx: float, ty: float):
    """Leva a ponta (landmark 8) até a posição normalizada (tx, ty)."""
    return _shift(hand, tx - hand[8][0], ty - hand[8][1])


class _Clock:
    def __init__(self, t: float = 2000.0) -> None:
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


# ── Leitura de texto ───────────────────────────────────────────────────
def test_read_text_lines_utf8_and_cp1252(tmp_path):
    utf = tmp_path / "u.txt"
    utf.write_text("olá\nmundo\n", encoding="utf-8")
    assert read_text_lines(utf) == ["olá", "mundo"]
    lat = tmp_path / "l.txt"
    lat.write_bytes("café\r\nação\r\n".encode("cp1252"))
    assert read_text_lines(lat) == ["café", "ação"]
    big = tmp_path / "g.txt"
    big.write_text("\n".join(str(i) for i in range(1000)), encoding="utf-8")
    assert len(read_text_lines(big)) == 400  # teto de linhas


def test_read_text_lines_handles_undecodable_bytes(tmp_path):
    p = tmp_path / "b.txt"
    p.write_bytes(b"ok\n\xff\xfequebrado\n")
    lines = read_text_lines(p)
    assert lines[0] == "ok"
    assert len(lines) == 2  # nunca lança: utf-8 falha, cp1252 cobre


# ── Deformação em perspectiva (a página "gira em 3D") ──────────────────
def _page(w=200, h=100):
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    surf.fill((240, 240, 240, 255))
    return surf


def test_warp_identity_for_small_angles():
    surf = _page()
    assert warp_yaw(surf, 0.0) is surf
    assert warp_yaw(surf, 0.01) is surf
    assert warp_pitch(surf, 0.01) is surf


def test_warp_yaw_narrows_the_page():
    src = _page()
    out = warp_yaw(src, 0.7)
    assert out is not src
    assert out.get_width() < src.get_width()     # afina com a rotação
    assert out.get_height() >= src.get_height()  # lado mais perto cresce


def test_warp_pitch_shrinks_height_and_widens():
    src = _page()
    out = warp_pitch(src, 0.6)
    assert out is not src
    assert out.get_height() < src.get_height()
    assert out.get_width() >= src.get_width()


def test_warp_handles_tiny_surface():
    tiny = pygame.Surface((1, 1), pygame.SRCALPHA)
    assert warp_yaw(tiny, 0.5) is tiny
    assert warp_pitch(tiny, 0.5) is tiny


# ── Carregador de modelo 3D ────────────────────────────────────────────
def test_load_obj_parses_quads_as_triangles(tmp_path):
    p = tmp_path / "cubo.obj"
    p.write_text(OBJ_CUBE, encoding="utf-8")
    mesh = load_obj(p)
    assert len(mesh.verts) == 8
    assert mesh.face_count == 12            # 6 quads -> 12 triângulos
    assert mesh.verts.min() >= -1.0 and mesh.verts.max() <= 1.0  # normalizado


def test_load_obj_relative_and_invalid_indices(tmp_path):
    p = tmp_path / "rel.obj"
    p.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\n", encoding="utf-8")
    assert load_obj(p).face_count == 1
    bad = tmp_path / "bad.obj"
    bad.write_text("v 0 0 0\nf 1 2 3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_obj(bad)


def test_load_stl_ascii_and_reject_binary(tmp_path):
    p = tmp_path / "t.stl"
    p.write_text(STL_TRI, encoding="utf-8")
    mesh = load_stl(p)
    assert len(mesh.verts) == 3 and mesh.face_count == 1
    binp = tmp_path / "b.stl"
    binp.write_bytes(b"\x00" * 80 + b"\x01\x00\x00\x00")
    with pytest.raises(ValueError, match="binário"):
        load_stl(binp)


def test_load_mesh_rejects_gltf(tmp_path):
    p = tmp_path / "modelo.glb"
    p.write_bytes(b"glTF")
    with pytest.raises(ValueError, match="renderizador"):
        load_mesh(p)


def test_load_obj_with_mtl_uses_material_colors(tmp_path):
    (tmp_path / "cor.mtl").write_text(
        "newmtl skin\nKd 1.0 0.5 0.2\n", encoding="utf-8")
    p = tmp_path / "m.obj"
    p.write_text("mtllib cor.mtl\nusemtl skin\n" + OBJ_CUBE, encoding="utf-8")
    mesh = load_obj(p)
    assert mesh.face_colors is not None
    assert tuple(int(c) for c in mesh.face_colors[0]) == (255, 128, 51)
    # sem .mtl -> face_colors None (o HUD cai no roxo de fallback)
    plain = tmp_path / "p.obj"
    plain.write_text(OBJ_CUBE, encoding="utf-8")
    assert load_obj(plain).face_colors is None


def test_render_mesh_draws_something(tmp_path):
    p = tmp_path / "cubo.obj"
    p.write_text(OBJ_CUBE, encoding="utf-8")
    surf = render_mesh(load_obj(p), 240, 180, yaw=0.7, pitch=0.4)
    assert surf.get_size() == (240, 180)
    assert surf.get_bounding_rect().width > 40  # tem pixels visíveis
    flat = render_mesh(load_obj(p), 120, 120, yaw=0.0, pitch=0.0)
    assert flat.get_bounding_rect().height > 40


# ── Estado da aba ──────────────────────────────────────────────────────
def test_doc_viewer_open_text_scroll_and_close(tmp_path):
    doc = tmp_path / "nota.txt"
    doc.write_text("\n".join(f"linha {i}" for i in range(200)), encoding="utf-8")
    v = DocViewer()
    assert v.visible is False
    lines = v.open_text(doc, center=(450, 400))
    assert v.visible and v.kind == "text"
    assert v.name == "nota.txt" and len(lines) == 200
    assert (v.x, v.y) == (450, 400)
    assert (v.yaw, v.pitch, v.scale) == (0.0, 0.0, 1.0)  # texto abre chapado
    v.scroll_by_lines(10)
    assert v.scroll == 10
    v.scroll_by_lines(10_000)
    assert v.scroll == v.max_scroll() > 0
    v.scroll_by_lines(-10_000)
    assert v.scroll == 0
    assert v.hit(450, 400) and not v.hit(4000, 400)
    rev = v.rev
    v.close()
    assert v.visible is False and v.rev > rev


def test_doc_viewer_model_pose_and_gesture_limits(tmp_path):
    p = tmp_path / "capacete.obj"
    p.write_text(OBJ_CUBE, encoding="utf-8")
    v = DocViewer()
    v.open_model(p, load_obj(p), center=(640, 400))
    assert v.kind == "model" and v.mesh is not None
    assert v.yaw == pytest.approx(0.7) and v.pitch == pytest.approx(0.4)  # 3/4
    v.rotate(0.5)
    # giro do gesto empurra yaw e pitch juntos (1 eixo só na câmera)
    assert v.yaw == pytest.approx(1.2)
    assert v.pitch == pytest.approx(0.65)
    for _ in range(40):
        v.rotate(1.0)
    assert v.yaw == YAW_MAX and v.pitch == PITCH_MAX
    v.zoom(99.0)
    assert v.scale == SCALE_MAX
    v.zoom(0.0)
    assert v.scale == SCALE_MIN
    assert v.max_scroll() == 0.0  # modelo não rola


def test_doc_viewer_geometry_follows_rotation(tmp_path):
    doc = tmp_path / "n.txt"
    doc.write_text("texto", encoding="utf-8")
    v = DocViewer()
    v.open_text(doc, center=(640, 400))
    wide = v.body_rect().width
    v.rotate(1.2)
    assert v.body_rect().width < wide          # de lado, afinou
    assert v.title_rect().bottom <= v.body_rect().top
    assert v.close_rect().collidepoint(v.close_rect().center)


# ── Tap confiável (o "só reconhece às vezes") ──────────────────────────
def _pinch_release(h, clock, card):
    h._process_hands([_hand(pinched=True)])
    assert h._ws_grab is card
    clock.t += 0.15
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.05
    h._process_hands([_shift(_hand(), -0.03, 0.27)])  # solta em (729.6, 360)


def test_hud_tap_on_text_card_opens_reading_tab(hud, tmp_path):
    h, clock = hud
    doc = tmp_path / "nota.txt"
    doc.write_text("primeira\nsegunda\nterceira", encoding="utf-8")
    h.workspace._current_path = tmp_path
    card = WorkspaceItem(id="tmp/nota.txt", name="nota.txt", kind="file",
                         x=729.6, y=360.0)
    h.workspace.items = [card]
    _pinch_release(h, clock, card)
    assert h.gesture_stats["tap"] == 1
    assert h.viewer.visible and h.viewer.kind == "text"
    assert h.viewer.lines[:3] == ["primeira", "segunda", "terceira"]
    assert h.viewer.hit(h.viewer.x, h.viewer.y)


def test_hud_tap_on_model_card_opens_3d_viewer(hud, tmp_path):
    h, clock = hud
    p = tmp_path / "capacete.obj"
    p.write_text(OBJ_CUBE, encoding="utf-8")
    h.workspace._current_path = tmp_path
    card = WorkspaceItem(id="tmp/capacete.obj", name="capacete.obj",
                         kind="model3d", x=729.6, y=360.0)
    h.workspace.items = [card]
    _pinch_release(h, clock, card)
    assert h.gesture_stats["tap"] == 1
    assert h.viewer.visible and h.viewer.kind == "model"
    assert h.viewer.mesh is not None and h.viewer.mesh.face_count == 12


def test_hud_unsupported_file_does_not_open_tab(hud, tmp_path):
    h, clock = hud
    p = tmp_path / "imagem.glb"
    p.write_bytes(b"glTF")
    h.workspace._current_path = tmp_path
    card = WorkspaceItem(id="tmp/imagem.glb", name="imagem.glb",
                         kind="model3d", x=729.6, y=360.0)
    h.workspace.items = [card]
    _pinch_release(h, clock, card)
    assert h.viewer.visible is False
    assert h.gesture_stats["tap"] == 1  # tap aconteceu; só o formato falhou


def test_hud_tap_works_when_pinch_started_off_the_card(hud):
    """Pinça começou no vazio e soltou em cima do card: tinha que abrir."""
    h, clock = hud
    card = WorkspaceItem(id="docs/sub", name="sub", kind="folder",
                         x=729.6, y=360.0)
    h.workspace.items = [card]
    far = _shift(_hand(pinched=True), 0.30)  # sx=345, longe do card e do central
    h._process_hands([far])
    assert h._ws_grab is None and h.dragging is None
    clock.t += 0.10
    h._process_hands([far])
    clock.t += 0.05
    h._process_hands([_shift(_hand(), -0.03, 0.27)])  # solta ONDE o card está
    assert h.gesture_stats["tap"] == 1
    assert card.open is True  # entrou/expandiu


def test_hud_hand_lost_releases_at_last_position(hud):
    """Mão caiu no quadro do tap: soltura vale na última posição, não (0,0)."""
    h, clock = hud
    card = WorkspaceItem(id="docs/sub", name="sub", kind="folder",
                         x=729.6, y=360.0)
    h.workspace.items = [card]
    h._process_hands([_hand(pinched=True)])
    assert h._ws_grab is card
    clock.t += 0.10
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.05
    h._process_hands([])  # MediaPipe perdeu a mão exatamente na soltura
    assert h.gesture_stats["tap"] == 1
    assert card.open is True
    assert h._pinch[0].armed is False


def test_hud_stationary_hold_still_taps_not_places(hud):
    """Mirar/devagar segurando o card parado é tap — não vira place."""
    h, clock = hud
    card = WorkspaceItem(id="docs/sub", name="sub", kind="folder",
                         x=729.6, y=360.0)
    h.workspace.items = [card]
    h._process_hands([_hand(pinched=True)])
    for _ in range(12):  # 1.2s parado em cima do card
        clock.t += 0.10
        h._process_hands([_hand(pinched=True)])
    assert clock.t - 2000.0 > TAP_MAX_DUR
    clock.t += 0.05
    h._process_hands([_shift(_hand(), -0.03, 0.27)])
    assert h.gesture_stats["tap"] == 1
    assert h.gesture_stats["place"] == 0
    assert card.open is True


def test_hud_release_fires_exactly_once_per_pinch(hud, monkeypatch):
    """Mão aberta em cima do botão não repetia a ação (re-fire por quadro)."""
    h, clock = hud
    calls = []
    monkeypatch.setattr(h, "open_folder_gesture", lambda: calls.append(1))
    button = pygame.Rect(int(729.6) - 16, 360 - 16, 32, 32)
    monkeypatch.setattr(h, "_chrome_buttons", lambda: {"folder": button})
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.10
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.05
    h._process_hands([_shift(_hand(), -0.03, 0.27)])
    assert calls == [1]
    for _ in range(5):  # mão continua aberta em cima do botão
        clock.t += 0.03
        h._process_hands([_shift(_hand(), -0.03, 0.27)])
    assert calls == [1]  # sem re-fire (armed = 1 soltura por pinça)


# ── Gestos na aba ──────────────────────────────────────────────────────
def _open_viewer(h, kind="text"):
    h.viewer.visible = True
    h.viewer.kind = kind
    h.viewer.x, h.viewer.y = 450.0, 400.0
    h.viewer.yaw = h.viewer.pitch = 0.0
    h.viewer.scale = 1.0


def test_hud_two_hands_rotate_and_zoom_the_open_tab(hud):
    h, clock = hud
    _open_viewer(h)
    left = _at(_hand(pinched=True), 0.33, 0.45)
    right = _at(_hand(pinched=True), 0.53, 0.45)
    h._process_hands([left, right])           # quadro base (grace)
    clock.t += 0.05
    h._process_hands([_at(left, 0.33, 0.50), _at(right, 0.53, 0.40)])
    clock.t += 0.10                            # passa a grace (0.0999+0.05 < 0.1)
    h._process_hands([_at(left, 0.33, 0.55), _at(right, 0.53, 0.35)])
    assert h.viewer.yaw > 0.0 and h.viewer.pitch > 0.0  # girou em 3D
    assert h.gesture_stats["tap"] == 0
    # Abre as mãos na mesma inclinação = zoom
    clock.t += 0.05
    h._process_hands([_at(left, 0.28, 0.55), _at(right, 0.58, 0.35)])
    assert h.viewer.scale > 1.0
    assert h.gesture_stats["zoom"] > 0


def test_hud_two_hands_pan_the_open_tab(hud):
    h, clock = hud
    _open_viewer(h)
    left = _at(_hand(pinched=True), 0.33, 0.45)
    right = _at(_hand(pinched=True), 0.53, 0.45)
    h._process_hands([left, right])
    for i in range(1, 6):
        clock.t += 0.05
        dy = -0.01 * i  # as duas mãos sobem juntas = pan pelo ponto médio
        h._process_hands([_at(left, 0.33, 0.45 + dy),
                          _at(right, 0.53, 0.45 + dy)])
    assert h.viewer.y < 400.0  # a aba subiu
    assert h.viewer.visible is True


def test_hud_drag_text_scrolls_and_release_keeps_tab_open(hud, tmp_path):
    h, clock = hud
    doc = tmp_path / "grande.txt"
    doc.write_text("\n".join(f"linha {i}" for i in range(300)), encoding="utf-8")
    h.viewer.open_text(doc, center=(450, 400))
    h._process_hands([_hand(pinched=True)])   # pinça dentro da aba
    assert h._viewer_drag is not None and h._viewer_drag[2] == "scroll"
    for i in range(1, 5):                      # dedo pra cima = rola a página
        clock.t += 0.05
        h._process_hands([_shift(_hand(pinched=True), 0.0, -0.04 * i)])
    assert h.viewer.scroll > 0
    clock.t += 0.05
    h._process_hands([_shift(_hand(), 0.0, -0.16)])
    assert h.viewer.visible is True           # rolar não fecha o doc
    assert h.gesture_stats["tap"] == 0


def test_hud_tap_on_open_tab_closes_it(hud, tmp_path):
    h, clock = hud
    doc = tmp_path / "nota.txt"
    doc.write_text("texto", encoding="utf-8")
    h.viewer.open_text(doc, center=(450, 400))
    h._process_hands([_hand(pinched=True)])   # (729.6, 360) dentro da aba
    clock.t += 0.12
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.05
    h._process_hands([_shift(_hand(), -0.03, 0.27)])
    assert h.viewer.visible is True           # 1 tap só registra
    assert h.gesture_stats["tap"] == 1
    clock.t += 0.10                            # 2º tap dentro da janela de 0.6s
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.12
    h._process_hands([_hand(pinched=True)])
    clock.t += 0.05
    h._process_hands([_shift(_hand(), -0.03, 0.27)])
    assert h.viewer.visible is False           # 2 taps fecham
    assert h.gesture_stats["tap"] == 2


def test_hud_second_tap_after_window_does_not_close(hud, tmp_path):
    h, clock = hud
    doc = tmp_path / "nota.txt"
    doc.write_text("texto", encoding="utf-8")
    h.viewer.open_text(doc, center=(450, 400))
    for _ in range(2):
        h._process_hands([_hand(pinched=True)])
        clock.t += 0.12
        h._process_hands([_hand(pinched=True)])
        clock.t += 0.05
        h._process_hands([_shift(_hand(), -0.03, 0.27)])
        clock.t += 1.0                        # janela de 0.6s estourou
    assert h.viewer.visible is True           # taps distantes não fecham
    assert h.gesture_stats["tap"] == 2


def test_hud_mouse_click_on_back_returns_to_previous_folder(hud):
    h, _clock = hud
    prev_items = [WorkspaceItem(id="docs/a", name="a", kind="folder",
                                x=400.0, y=300.0)]
    h.workspace.items = [WorkspaceItem(id="docs/sub", name="sub",
                                       kind="folder", x=400.0, y=300.0)]
    h.workspace.current = "sub"
    h.workspace._stack.append(("docs", None, prev_items))
    h.workspace._append_back()
    assert any(it.kind == "back" for it in h.workspace.items)
    pos = (350, 690)                          # card VOLTAR (x=350, y=690)
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                         button=1, pos=pos))
    h._handle_events()
    assert h._ws_mouse is not None            # mouse agarrou o card
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP,
                                         button=1, pos=pos))
    h._handle_events()
    assert h._ws_mouse is None
    assert h.workspace.items is prev_items    # voltou para a vista anterior


def test_hud_gesture_tap_on_back_returns(hud):
    h, clock = hud
    prev_items = [WorkspaceItem(id="docs/a", name="a", kind="folder",
                                x=400.0, y=300.0)]
    h.workspace.items = [WorkspaceItem(id="docs/sub", name="sub",
                                       kind="folder", x=400.0, y=300.0)]
    h.workspace._stack.append(("docs", None, prev_items))
    h.workspace._append_back()
    back = next(it for it in h.workspace.items if it.kind == "back")
    # soltura em (350, 690): landmark8 normalizado com espelho ((1-x)*1280)
    fx, fy = 1.0 - back.x / 1280.0, back.y / 800.0
    h._process_hands([_at(_hand(pinched=True), fx, fy)])
    assert h._ws_grab is None                 # grab_at exclui o VOLTAR...
    assert h.dragging is None                 # ...e ele está fora do holo
    clock.t += 0.12
    h._process_hands([_at(_hand(pinched=True), fx, fy)])
    clock.t += 0.05
    h._process_hands([_at(_hand(), fx, fy)])
    assert h.gesture_stats["tap"] == 1
    assert h.workspace.items is prev_items    # gesto também volta


def test_hud_image_card_opens_image_tab(hud, tmp_path):
    h, clock = hud
    from PIL import Image
    img = tmp_path / "foto.png"
    Image.new("RGB", (48, 36), (12, 200, 90)).save(img)
    h.workspace._current_path = tmp_path
    card = WorkspaceItem(id="tmp/foto.png", name="foto.png", kind="file",
                         cat="image", x=729.6, y=360.0)
    h.workspace.items = [card]
    _pinch_release(h, clock, card)
    assert h.viewer.visible and h.viewer.kind == "image"
    assert h.viewer.image is not None


def test_hud_archive_card_lists_contents(hud, tmp_path):
    h, clock = hud
    import zipfile
    z = tmp_path / "pacote.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.txt", "oi")
        zf.writestr("sub/b.png", b"\x89PNG\r\n")
    h.workspace._current_path = tmp_path
    card = WorkspaceItem(id="tmp/pacote.zip", name="pacote.zip", kind="file",
                         cat="archive", x=729.6, y=360.0)
    h.workspace.items = [card]
    _pinch_release(h, clock, card)
    assert h.viewer.visible and h.viewer.kind == "text"
    assert any("a.txt" in ln for ln in h.viewer.lines)
    assert any("b.png" in ln for ln in h.viewer.lines)


def test_hud_two_hand_gesture_does_not_become_tap_on_release(hud):
    """Girar a aba com 2 mãos e soltar não pode fechar nada."""
    h, clock = hud
    _open_viewer(h)
    left = _at(_hand(pinched=True), 0.33, 0.45)
    right = _at(_hand(pinched=True), 0.53, 0.45)
    h._process_hands([left, right])
    clock.t += 0.05
    h._process_hands([_at(left, 0.33, 0.55), _at(right, 0.53, 0.35)])
    clock.t += 0.05
    h._process_hands([_at(_hand(), 0.33, 0.55), _at(_hand(), 0.53, 0.35)])
    assert h.viewer.visible is True
    assert h.gesture_stats["tap"] == 0


def _fist():
    pts = [list(p) for p in _BASE]
    pts[8] = [0.46, 0.60]
    pts[12] = [0.52, 0.60]
    pts[16] = [0.61, 0.60]
    pts[20] = [0.70, 0.62]
    pts[4] = [0.44, 0.58]
    return [(x, y) for x, y in pts]


def test_hud_reset_closes_the_open_tab(hud):
    h, clock = hud
    _open_viewer(h)
    h.settings_open = True
    hands = [_fist(), _shift(_fist(), 0.20)]
    h._process_hands(hands)
    clock.t += 1.1
    h._process_hands(hands)
    assert h.gesture_stats["reset"] == 1
    assert h.viewer.visible is False
    assert h.settings_open is False


# ── Integração HandPinch (tap por distância, não só por duração) ──────
def test_handpinch_records_start_point_and_armed():
    p = HandPinch(speed_aware=True)
    assert p.armed is False
    p.update(0.20, 100.0, 50.0, 10.0)
    assert p.armed is True
    assert (p.down_x, p.down_y) == (100.0, 50.0)
    assert p.moved(100.0, 50.0) == 0.0
    assert p.moved(130.0, 90.0) == 50.0
    assert TAP_MAX_MOVE < 90.0
    p.reset()
    assert p.armed is False
    assert p.pinched is False


def test_handpinch_tap_rules_are_speed_safe():
    p = HandPinch(speed_aware=True)
    p.update(0.20, 0.0, 0.0, 5.0)
    assert p.is_tap(5.0 + TAP_MAX_DUR) is True
    assert p.is_tap(5.1 + TAP_MAX_DUR) is False
    assert p.moved(40.0, 0.0) <= TAP_MAX_MOVE
    assert p.moved(200.0, 0.0) > TAP_MAX_MOVE
    # soltura rápida (>SPEED_FAST) não pode virar tap
    t = 5.2
    for i in range(1, 6):
        t += 0.010
        p.update(0.20, 60.0 * i, 0.0, t)
    assert p.last_speed > SPEED_FAST
    assert math.isfinite(p.last_speed)
