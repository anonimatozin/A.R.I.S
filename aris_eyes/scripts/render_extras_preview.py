"""Gera docs/preview_extras.png: os humores novos com seus props (roda sem tela: plataforma 'offscreen').

    python scripts/render_extras_preview.py            # galeria dos humores novos
    python scripts/render_extras_preview.py --scenes   # galeria das cenas (spotify, fone, ...)
"""
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from aris_eyes.config import Config
from aris_eyes.eyes.animator import EyeAnimator, IdleSettings
from aris_eyes.eyes.presets import MOOD_ORDER, MOOD_PROPS, Mood
from aris_eyes.eyes.props import PropEngine
from aris_eyes.eyes.props_renderer import draw_props
from aris_eyes.eyes.renderer import Theme, draw_eyes

COLS, CELL_W, CELL_H = 3, 500, 300
NEW_MOODS = tuple(MOOD_ORDER[12:])
SIM_SECONDS = 2.2


def simulate(mood: Mood, extra_props=(), accent=None, seconds=SIM_SECONDS):
    rng = random.Random(7)
    anim = EyeAnimator(IdleSettings(saccades=False, breathing=False), mood, rng)
    eng = PropEngine(random.Random(3))
    eng.sync_mood(MOOD_PROPS.get(mood, ()))
    for name in extra_props:
        eng.add(name)
    frame = pframe = None
    for _ in range(int(seconds * 60)):
        frame = anim.update(1 / 60)
        pframe = eng.update(1 / 60)
        if mood in (Mood.MUSIC, Mood.CHILL):
            anim.set_speech_level(eng.beat)
    return frame, pframe


def render(cells, out: Path) -> None:
    app = QApplication.instance() or QApplication([])
    theme = Theme.from_config(Config())
    rows = (len(cells) + COLS - 1) // COLS
    image = QImage(COLS * CELL_W, rows * CELL_H, QImage.Format.Format_ARGB32)
    image.fill(QColor("#101418"))
    p = QPainter(image)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    for i, (label, frame, pframe, accent) in enumerate(cells):
        x, y = (i % COLS) * CELL_W, (i // COLS) * CELL_H
        p.fillRect(QRectF(x + 4, y + 4, CELL_W - 8, CELL_H - 8), theme.background)
        area = QRectF(x + 12, y + 8, CELL_W - 24, CELL_H - 40)
        draw_eyes(p, frame, theme, area)
        draw_props(p, pframe, theme, area, frame, accent)
        p.setPen(QColor("#8aa4c8"))
        p.drawText(QRectF(x, y + CELL_H - 30, CELL_W, 24), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    out.parent.mkdir(exist_ok=True)
    image.save(str(out))
    print("salvo em", out)
    del app


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    if "--scenes" in sys.argv:
        from aris_eyes.eyes.scenes import SCENES
        cells = []
        for name, scene in SCENES.items():
            frame, pframe = simulate(scene.mood, scene.props, scene.accent)
            cells.append((f"cena: {name}", frame, pframe, scene.accent))
        render(cells, root / "docs" / "preview_scenes.png")
        return
    cells = []
    for mood in NEW_MOODS:
        frame, pframe = simulate(mood)
        cells.append((mood.value, frame, pframe, None))
    render(cells, root / "docs" / "preview_extras.png")


if __name__ == "__main__":
    main()
