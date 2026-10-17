"""Desenho dos olhos com QPainter. Funcao pura: recebe um Frame e pinta; nao guarda estado.

Cada olho e um retangulo arredondado. Palpebras (de cima e "bochecha" de baixo) sao formas
subtraidas do olho, o que permite bravo, triste, feliz (arco ^), sonolento, etc.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

from .animator import Frame

DESIGN_W, DESIGN_H = 1000.0, 560.0
CENTER_X, CENTER_Y = 500.0, 280.0
GAZE_RANGE_X, GAZE_RANGE_Y = 85.0, 50.0       # quanto os olhos andam ao olhar para um canto

# (largura, opacidade) do brilho. 3 camadas sem suavizacao de borda: o brilho e fraco e macio, entao a
# diferenca nao aparece, e custa ~3x menos que com suavizacao (que era o maior gasto de CPU).
_GLOW_LAYERS = ((38.0, 0.06), (24.0, 0.09), (12.0, 0.13))


@dataclass(frozen=True)
class Theme:
    eye: QColor
    eye_light: QColor
    glow: QColor
    background: QColor
    border: QColor
    glow_enabled: bool = True

    @classmethod
    def from_hex(cls, eye: str, glow: str, background: str, glow_enabled: bool = True) -> "Theme":
        eye_c, glow_c, bg_c = QColor(eye), QColor(glow), QColor(background)
        border = QColor(glow_c)
        border.setAlpha(110)
        return cls(eye=eye_c, eye_light=eye_c.lighter(145), glow=glow_c, background=bg_c, border=border,
                   glow_enabled=glow_enabled)

    @classmethod
    def from_config(cls, cfg) -> "Theme":
        return cls.from_hex(cfg.eye_color, cfg.glow_color, cfg.background_color, cfg.glow)


def draw_eyes(p: QPainter, frame: Frame, theme: Theme, area: QRectF) -> None:
    """Desenha o par de olhos centralizado em `area`, mantendo a proporcao do espaco de desenho."""
    scale = min(area.width() / DESIGN_W, area.height() / DESIGN_H)
    if scale <= 0.0:
        return
    eyes = [_build_eye(frame, side) for side in (-1, 1)]       # -1 = olho esquerdo, +1 = olho direito

    eye_opacity = 1.0 - frame.x_mix
    if theme.glow_enabled and eye_opacity > 0.01 and frame.glow > 0.01:
        p.save()
        p.setOpacity(eye_opacity)
        _draw_glow(p, [e[0] for e in eyes], frame, theme, area, scale)
        p.restore()

    p.save()
    p.translate(area.center())
    p.scale(scale, scale)
    p.translate(-CENTER_X, -CENTER_Y)
    for path, rect, cx, cy in eyes:
        if eye_opacity > 0.01 and not path.isEmpty():
            p.save()
            p.setOpacity(eye_opacity)
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0.0, theme.eye_light)
            gradient.setColorAt(1.0, theme.eye)
            p.setPen(Qt.PenStyle.NoPen)
            p.fillPath(path, gradient)
            p.restore()
        if frame.x_mix > 0.01:                                 # olhos em X (erro)
            p.save()
            p.setOpacity(frame.x_mix)
            half = min(frame.w, frame.h) * 0.34
            pen = QPen(theme.eye_light, 30.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(cx - half, cy - half), QPointF(cx + half, cy + half))
            p.drawLine(QPointF(cx - half, cy + half), QPointF(cx + half, cy - half))
            p.restore()
    p.restore()


def _draw_glow(p: QPainter, paths: list, frame: Frame, theme: Theme, area: QRectF, scale: float) -> None:
    """Brilho em volta dos olhos: contornos largos e fracos empilhados."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.translate(area.center())
    p.scale(scale, scale)
    p.translate(-CENTER_X, -CENTER_Y)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for width, alpha in _GLOW_LAYERS:
        color = QColor(theme.glow)
        color.setAlphaF(min(1.0, alpha * frame.glow))
        pen = QPen(color, width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        for path in paths:
            if not path.isEmpty():
                p.drawPath(path)
    p.restore()


def _eye_geometry(frame: Frame, side: int):
    sc = 1.0 - side * frame.asym * 0.12                       # pensando: um olho menor
    squint = 1.0 - max(0.0, side * frame.asym) * 0.30         # e mais estreito
    ew = frame.w * sc
    eh = max(frame.h * sc * frame.open * squint, 7.0)
    cx = CENTER_X + side * (frame.gap / 2.0 + frame.w / 2.0) + frame.gx * GAZE_RANGE_X
    cy = CENTER_Y + frame.dy + frame.gy * GAZE_RANGE_Y
    return cx, cy, ew, eh


def _build_eye(frame: Frame, side: int):
    """Forma de um olho (ja com palpebras). Devolve (path, rect, cx, cy) em unidades de desenho."""
    cx, cy, ew, eh = _eye_geometry(frame, side)
    rect = QRectF(cx - ew / 2.0, cy - eh / 2.0, ew, eh)
    radius = frame.round * min(ew, eh) / 2.0
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    # palpebra de cima (reta ou inclinada)
    if frame.lid_top > 0.002 or abs(frame.lid_slant) > 0.002:
        y0 = rect.top() + frame.lid_top * eh
        s = frame.lid_slant * eh * 0.25
        y_left, y_right = y0 + side * s, y0 - side * s        # canto interno fica mais baixo se slant > 0
        pad = 40.0
        lid = QPainterPath()
        lid.addPolygon(QPolygonF([
            QPointF(rect.left() - pad, rect.top() - pad), QPointF(rect.right() + pad, rect.top() - pad),
            QPointF(rect.right() + pad, y_right), QPointF(rect.left() - pad, y_left)]))
        lid.closeSubpath()
        path = path.subtracted(lid)

    # "bochecha" que sobe por baixo: deixa o olho em arco (feliz)
    if frame.lid_bottom > 0.002:
        ell_w, ell_h = ew * 1.4, eh * 1.35
        center_y = rect.bottom() + ell_h / 2.0 - frame.lid_bottom * eh * 1.05
        cheek = QPainterPath()
        cheek.addEllipse(QPointF(cx, center_y), ell_w / 2.0, ell_h / 2.0)
        path = path.subtracted(cheek)

    return path, rect, cx, cy
