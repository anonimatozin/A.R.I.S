"""Gera docs/preview.png com todas as expressoes (roda sem tela: usa a plataforma 'offscreen').

    python scripts/render_preview.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from aris_eyes.config import Config
from aris_eyes.eyes.animator import EyeAnimator, IdleSettings
from aris_eyes.eyes.presets import MOOD_ORDER
from aris_eyes.eyes.renderer import Theme, draw_eyes

COLS, CELL_W, CELL_H = 4, 400, 224


def main() -> None:
    app = QApplication([])
    cfg = Config()
    theme = Theme.from_config(cfg)
    rows = (len(MOOD_ORDER) + COLS - 1) // COLS
    image = QImage(COLS * CELL_W, rows * CELL_H, QImage.Format.Format_ARGB32)
    image.fill(QColor("#101418"))
    p = QPainter(image)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    for i, mood in enumerate(MOOD_ORDER):
        anim = EyeAnimator(IdleSettings(saccades=False, breathing=False), mood)
        frame = anim.update(0.0)
        x, y = (i % COLS) * CELL_W, (i // COLS) * CELL_H
        p.fillRect(QRectF(x + 4, y + 4, CELL_W - 8, CELL_H - 8), theme.background)
        draw_eyes(p, frame, theme, QRectF(x + 12, y + 8, CELL_W - 24, CELL_H - 40))
        p.setPen(QColor("#8aa4c8"))
        p.drawText(QRectF(x, y + CELL_H - 30, CELL_W, 24), Qt.AlignmentFlag.AlignCenter, mood.value)
    p.end()
    out = Path(__file__).resolve().parent.parent / "docs" / "preview.png"
    out.parent.mkdir(exist_ok=True)
    image.save(str(out))
    print("salvo em", out)
    del app


if __name__ == "__main__":
    main()
