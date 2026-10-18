"""Testes do motor de props (sem Qt) e do desenho dos props (Qt offscreen)."""
import random

import pytest

from aris_eyes.eyes.presets import MOOD_PROPS, PRESETS, Mood
from aris_eyes.eyes.props import BAR_COUNT, MAX_PARTICLES, PROP_NAMES, PropEngine


def run(engine, seconds, dt=1 / 60):
    frame = None
    for _ in range(int(seconds / dt)):
        frame = engine.update(dt)
    return frame


def kinds(frame):
    return {it.kind for it in frame.items}


def make(seed=1):
    return PropEngine(random.Random(seed))


def test_todo_prop_conhecido_e_aceito_e_desconhecido_e_recusado():
    e = make()
    assert all(e.add(name) for name in PROP_NAMES)
    assert e.add("nao-existe") is False
    assert e.add("") is False


def test_prop_aparece_e_some_com_fade():
    e = make()
    e.add("headphones")
    frame = run(e, 0.5)
    item = next(i for i in frame.items if i.kind == "headphones")
    assert item.alpha > 0.95
    e.remove("headphones")
    mid = e.update(0.05)
    assert any(i.kind == "headphones" and 0.0 < i.alpha < 1.0 for i in mid.items)   # sumindo, nao cortado
    run(e, 1.0)
    assert not e.is_animating


def test_prop_com_tempo_expira_sozinho():
    e = make()
    e.add("wink")                                     # padrao: 1,2 s
    assert "wink" in kinds(run(e, 0.6))
    assert "wink" not in kinds(run(e, 1.6))
    assert "wink" not in e.active_names()


def test_prop_manual_com_segundos_explicitos():
    e = make()
    e.add("hearts", seconds=0.5)
    run(e, 0.3)
    assert "hearts" in e.active_names()
    run(e, 0.5)
    assert "hearts" not in e.active_names()


def test_sync_mood_troca_props_do_humor_e_preserva_os_manuais():
    e = make()
    e.add("battery")
    e.sync_mood(MOOD_PROPS[Mood.MUSIC])
    assert e.active_names() == {"battery", "notes", "equalizer"}
    e.sync_mood(MOOD_PROPS[Mood.LOVE])
    assert e.active_names() == {"battery", "eye_heart", "hearts"}
    e.sync_mood(())
    assert e.active_names() == {"battery"}


def test_sync_mood_ignora_nomes_invalidos():
    e = make()
    e.sync_mood(("notes", "xpto"))
    assert e.active_names() == {"notes"}


def test_particulas_nascem_e_o_total_fica_limitado():
    e = make()
    for name in ("notes", "hearts", "sparkles", "tears", "zzz"):
        e.add(name)
    peak = 0
    for _ in range(60 * 30):                          # 30 s
        frame = e.update(1 / 60)
        peak = max(peak, len(frame.items))
    assert 0 < peak
    assert len(e._parts) <= MAX_PARTICLES + 5


def test_confete_explode_uma_vez_e_acaba():
    e = make()
    e.add("confetti")
    frame = run(e, 0.4)
    assert sum(1 for i in frame.items if i.kind == "confetti") >= 40
    run(e, 6.0)
    assert not e._parts and not e.is_animating


def test_beat_fica_entre_0_e_1_e_o_volume_escala_a_batida():
    e = make()
    peak_free = max(e.update(1 / 60).beat for _ in range(240))
    assert 0.9 < peak_free <= 1.0
    e2 = make()
    e2.set_level(0.0)
    peak_quiet = max(e2.update(1 / 60).beat for _ in range(240))
    assert 0.3 < peak_quiet < 0.4
    e2.set_level(None)
    assert max(e2.update(1 / 60).beat for _ in range(240)) > 0.9


def test_equalizador_tem_barras_validas():
    e = make()
    e.add("equalizer")
    frame = run(e, 1.0)
    bars = next(i for i in frame.items if i.kind == "equalizer").data
    assert len(bars) == BAR_COUNT and all(0.0 <= b <= 1.0 for b in bars)


def test_mesma_semente_gera_o_mesmo_resultado():
    def snapshot(seed):
        e = make(seed)
        e.add("notes"); e.add("hearts")
        f = run(e, 3.0)
        return [(i.kind, round(i.x, 3), round(i.y, 3)) for i in f.items]
    assert snapshot(5) == snapshot(5)
    assert snapshot(5) != snapshot(6)


def test_dt_gigante_nao_quebra_nada():
    e = make()
    e.add("notes")
    frame = e.update(50.0)                            # janela travou por 50 s
    assert frame.time <= 0.11


def test_props_de_todo_humor_existem():
    for mood, names in MOOD_PROPS.items():
        assert mood in PRESETS
        assert all(n in PROP_NAMES for n in names), mood


# ----------------------------------------------------------------- desenho (Qt offscreen)
QtGui = pytest.importorskip("PySide6.QtGui")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def paint(qapp, engine, frame=None, accent=None, size=(500, 280), bg="#000000"):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from aris_eyes.config import Config
    from aris_eyes.eyes.animator import Frame
    from aris_eyes.eyes.props_renderer import draw_props
    from aris_eyes.eyes.renderer import Theme

    theme = Theme.from_config(Config())
    image = QImage(size[0], size[1], QImage.Format.Format_ARGB32)
    image.fill(QColor(bg))
    p = QPainter(image)
    pframe = run(engine, 1.5)
    draw_props(p, pframe, theme, QRectF(0, 0, *size), frame or Frame(), accent)
    p.end()
    return image


def lit_pixels(image, bg="#000000"):
    """Quantos pixels (amostrados) diferem da cor de fundo."""
    from PySide6.QtGui import QColor
    ref = QColor(bg)
    w, h = image.width(), image.height()
    count = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            c = image.pixelColor(x, y)
            if abs(c.red() - ref.red()) + abs(c.green() - ref.green()) + abs(c.blue() - ref.blue()) > 30:
                count += 1
    return count


@pytest.mark.parametrize("name", PROP_NAMES)
def test_cada_prop_desenha_algo_visivel(qapp, name):
    e = make()
    e.add(name, seconds=60)
    # a espiral e pintada na cor do fundo POR CIMA dos olhos: testa sobre um fundo azul
    bg = "#2f9bff" if name == "eye_spiral" else "#000000"
    assert lit_pixels(paint(qapp, e, bg=bg), bg) > 20, name


def test_sem_props_nao_desenha_nada(qapp):
    assert lit_pixels(paint(qapp, make())) == 0


def test_accent_invalido_ou_hex_nao_quebra(qapp):
    for accent in ("#1ed760", "nao-e-cor", "", None):
        e = make()
        e.add("notes"); e.add("equalizer"); e.add("headphones")
        assert lit_pixels(paint(qapp, e, accent=accent)) > 20


def test_accent_muda_a_cor(qapp):
    def dominant(accent):
        e = make()
        e.add("equalizer", seconds=60)
        img = paint(qapp, e, accent=accent)
        r = g = b = 0
        for y in range(0, img.height(), 2):
            for x in range(0, img.width(), 2):
                c = img.pixelColor(x, y)
                r, g, b = r + c.red(), g + c.green(), b + c.blue()
        return r, g, b
    r, g, b = dominant("#ff0000")
    assert r > g * 3 and r > b * 3
    r, g, b = dominant("#00ff00")
    assert g > r * 3 and g > b * 3


def test_tamanhos_extremos_nao_quebram(qapp):
    e = make()
    for name in PROP_NAMES:
        e.add(name, seconds=60)
    for size in ((1, 1), (40, 22), (1920, 1080)):
        paint(qapp, e, size=size)
