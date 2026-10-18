"""Desenho dos props com QPainter. Funcao pura: recebe um PropFrame e pinta; nao guarda estado.

Tudo e desenhado com caminhos (QPainterPath), sem fontes nem imagens externas: nao depende de nenhum
arquivo e fica igual em qualquer distribuicao Linux.

Uso (logo depois de ``draw_eyes``, com a mesma ``area``)::

    draw_eyes(p, frame, theme, area)
    draw_props(p, prop_frame, theme, area, frame, accent=None)

``accent`` (hex ou QColor) pinta notas, fone, equalizador e ondas; com o Spotify pode ser a cor da capa.
"""
from __future__ import annotations

import math
from typing import Optional, Union

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient

from .animator import Frame
from .props import BAR_COUNT, Item, PropFrame
from .renderer import CENTER_X, CENTER_Y, DESIGN_H, DESIGN_W, Theme, _eye_geometry

PINK = QColor("#ff5c8a")
GOLD = QColor("#ffd24a")
TEAR = QColor("#8fd0ff")
AMBER = QColor("#ffb020")
RED = QColor("#ff4d4d")
HEADSET = QColor("#1b2433")
HEADSET_LIGHT = QColor("#2c3a55")


def draw_props(p: QPainter, pframe: PropFrame, theme: Theme, area: QRectF, eye_frame: Optional[Frame] = None,
               accent: Union[str, QColor, None] = None) -> None:
    if not pframe.items:
        return
    scale = min(area.width() / DESIGN_W, area.height() / DESIGN_H)
    if scale <= 0.0:
        return
    frame = eye_frame or Frame()
    acc = QColor(accent) if accent else QColor(theme.glow).lighter(125)
    if not acc.isValid():
        acc = QColor(theme.glow).lighter(125)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(area.center())
    p.scale(scale, scale)
    p.translate(-CENTER_X, -CENTER_Y)
    for it in pframe.items:
        fn = _DRAWERS.get(it.kind)
        if fn is None or it.alpha <= 0.003:
            continue
        p.save()
        p.setOpacity(max(0.0, min(1.0, it.alpha)))
        fn(p, it, theme, acc, frame)
        p.restore()
    p.restore()


# ---------------------------------------------------------------------- formas basicas (unidade ~ 1)
def _heart_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(0.0, 0.95)
    path.cubicTo(-1.35, -0.05, -0.95, -1.05, 0.0, -0.4)
    path.cubicTo(0.95, -1.05, 1.35, -0.05, 0.0, 0.95)
    path.closeSubpath()
    return path


def _star_polygon(points: int, inner: float) -> QPolygonF:
    poly = QPolygonF()
    for i in range(points * 2):
        r = 1.0 if i % 2 == 0 else inner
        a = -math.pi / 2.0 + i * math.pi / points
        poly.append(QPointF(math.cos(a) * r, math.sin(a) * r))
    return poly


def _sparkle_polygon() -> QPolygonF:
    pts = [(0, -1), (0.2, -0.2), (1, 0), (0.2, 0.2), (0, 1), (-0.2, 0.2), (-1, 0), (-0.2, -0.2)]
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _note_path(double: bool) -> QPainterPath:
    path = QPainterPath()
    head = QPainterPath()
    head.addEllipse(QPointF(0.0, 0.0), 0.62, 0.44)
    if double:
        head.addEllipse(QPointF(-1.25, 0.4), 0.62, 0.44)
    path.addPath(head)
    stem = QPainterPath()
    stem.addRect(QRectF(0.5, -1.75, 0.15, 1.75))
    if double:
        stem.addRect(QRectF(-0.75, -1.35, 0.15, 1.75))
        beam = QPolygonF([QPointF(-0.75, -1.35), QPointF(0.65, -1.75), QPointF(0.65, -1.4), QPointF(-0.75, -1.0)])
        stem.addPolygon(beam)
    else:
        flag = QPainterPath()
        flag.moveTo(0.65, -1.75)
        flag.cubicTo(1.2, -1.25, 1.35, -0.8, 0.95, -0.35)
        flag.cubicTo(1.05, -0.85, 0.9, -1.15, 0.65, -1.2)
        flag.closeSubpath()
        stem.addPath(flag)
    path.addPath(stem)
    return path


def _teardrop_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(0.0, -1.0)
    path.cubicTo(0.2, -0.45, 0.85, 0.05, 0.85, 0.5)
    path.arcTo(QRectF(-0.85, -0.2, 1.7, 1.4), 0.0, -180.0)
    path.cubicTo(-0.85, 0.05, -0.2, -0.45, 0.0, -1.0)
    path.closeSubpath()
    return path


def _fill(p: QPainter, path: QPainterPath, color: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _at(p: QPainter, x: float, y: float, size: float, rot: float = 0.0) -> None:
    p.translate(x, y)
    if rot:
        p.rotate(math.degrees(rot))
    p.scale(size, size)


# ---------------------------------------------------------------------- particulas
def _draw_note(p, it: Item, theme, acc, frame) -> None:
    _at(p, it.x, it.y, it.size * 1.0, it.rot)
    _fill(p, _note_path(it.variant == 1), acc.lighter(115))


def _draw_heart(p, it: Item, theme, acc, frame) -> None:
    _at(p, it.x, it.y, it.size * 0.8, it.rot)
    _fill(p, _heart_path(), PINK)


def _draw_zzz(p, it: Item, theme, acc, frame) -> None:
    _at(p, it.x, it.y, it.size * 0.5, it.rot)
    pen = QPen(theme.eye_light, 0.38)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    z = QPainterPath()
    z.moveTo(-1.0, -1.0)
    z.lineTo(1.0, -1.0)
    z.lineTo(-1.0, 1.0)
    z.lineTo(1.0, 1.0)
    p.drawPath(z)


def _draw_sparkle(p, it: Item, theme, acc, frame) -> None:
    _at(p, it.x, it.y, it.size, it.rot)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffe98a"))
    p.drawPolygon(_sparkle_polygon())


def _draw_tear(p, it: Item, theme, acc, frame) -> None:
    _at(p, it.x, it.y, it.size)
    _fill(p, _teardrop_path(), TEAR)


def _draw_confetti(p, it: Item, theme, acc, frame) -> None:
    p.translate(it.x, it.y)
    p.rotate(math.degrees(it.rot))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(it.color or "#ffffff"))
    w = it.size
    h = it.size * (0.45 if it.variant else 0.9)
    p.drawRoundedRect(QRectF(-w / 2, -h / 2, w, h), 2.0, 2.0)


# ---------------------------------------------------------------------- olhos que viram icones
def _cover_eye(p: QPainter, theme: Theme, cx: float, cy: float, ew: float, eh: float) -> None:
    pad = 48.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.background)
    p.drawRoundedRect(QRectF(cx - ew / 2 - pad, cy - eh / 2 - pad, ew + 2 * pad, eh + 2 * pad), 90.0, 90.0)


def _sides(it: Item) -> tuple:
    return (-1, 1) if it.side == 0 else (it.side,)


def _draw_eye_heart(p, it: Item, theme, acc, frame) -> None:
    for side in _sides(it):
        cx, cy, ew, eh = _eye_geometry(frame, side)
        _cover_eye(p, theme, cx, cy, ew, eh)
        s = min(ew, eh) * 0.5 * it.size
        for width, alpha in ((0.55, 0.10), (0.34, 0.16), (0.18, 0.22)):      # brilho rosa
            glow = QColor(PINK)
            glow.setAlphaF(alpha)
            p.save()
            _at(p, cx, cy + s * 0.05, s)
            pen = QPen(glow, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(_heart_path())
            p.restore()
        p.save()
        _at(p, cx, cy + s * 0.05, s)
        _fill(p, _heart_path(), PINK)
        shine = QPainterPath()                                              # reflexo
        shine.addEllipse(QPointF(-0.5, -0.38), 0.2, 0.13)
        _fill(p, shine, QColor(255, 255, 255, 150))
        p.restore()


def _draw_eye_star(p, it: Item, theme, acc, frame) -> None:
    for side in _sides(it):
        cx, cy, ew, eh = _eye_geometry(frame, side)
        _cover_eye(p, theme, cx, cy, ew, eh)
        s = min(ew, eh) * 0.55 * it.size
        for width, alpha in ((0.5, 0.10), (0.3, 0.16), (0.16, 0.22)):
            glow = QColor(GOLD)
            glow.setAlphaF(alpha)
            p.save()
            _at(p, cx, cy, s, it.rot)
            pen = QPen(glow, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(_star_polygon(5, 0.45))
            p.restore()
        p.save()
        _at(p, cx, cy, s, it.rot)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(GOLD)
        p.drawPolygon(_star_polygon(5, 0.45))
        p.restore()


def _draw_eye_spiral(p, it: Item, theme, acc, frame) -> None:
    for side in _sides(it):
        cx, cy, ew, eh = _eye_geometry(frame, side)
        radius = min(ew, eh) * 0.44
        path = QPainterPath()
        turns, steps = 3.0, 90
        for i in range(steps + 1):
            u = i / steps
            a = u * turns * 2.0 * math.pi
            r = radius * (0.08 + 0.92 * u)
            pt = QPointF(math.cos(a) * r, math.sin(a) * r)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(it.rot) * (-side))
        pen = QPen(theme.background, 15.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.restore()


def _draw_wink(p, it: Item, theme, acc, frame) -> None:
    for side in _sides(it):
        cx, cy, ew, eh = _eye_geometry(frame, side)
        _cover_eye(p, theme, cx, cy, ew, eh)
        w = ew * 0.82
        arch = QPainterPath()
        arch.moveTo(cx - w / 2, cy + eh * 0.08)
        arch.cubicTo(cx - w / 2, cy - eh * 0.28, cx + w / 2, cy - eh * 0.28, cx + w / 2, cy + eh * 0.08)
        for width, color in ((64.0, QColor(theme.glow)), (42.0, QColor(theme.eye_light))):
            c = QColor(color)
            if width > 50:
                c.setAlphaF(0.22)
            pen = QPen(c, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(arch)


def _draw_blush(p, it: Item, theme, acc, frame) -> None:
    for side in (-1, 1):
        cx, cy, ew, eh = _eye_geometry(frame, side)
        x, y = cx + side * ew * 0.08, cy + eh / 2.0 + 6.0
        rx, ry = ew * 0.42, 34.0
        grad = QRadialGradient(QPointF(x, y), rx)
        c1, c2 = QColor("#ff7aa8"), QColor("#ff7aa8")
        c1.setAlphaF(0.85)
        c2.setAlphaF(0.0)
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)
        p.save()
        p.translate(x, y)
        p.scale(1.0, ry / rx)
        p.translate(-x, -y)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(x, y), rx, rx)
        p.restore()


# ---------------------------------------------------------------------- elementos fixos
def _draw_headphones(p, it: Item, theme, acc, frame) -> None:
    beat = it.data[0] if it.data else 0.0
    slide = (1.0 - it.alpha) * 50.0                                       # entra deslizando de cima
    p.translate(0.0, -7.0 * beat - slide)
    cx, cy, rx, ry = 500.0, 300.0, 408.0, 268.0
    rect = QRectF(cx - rx, cy - ry, 2 * rx, 2 * ry)
    band = QPainterPath()
    band.arcMoveTo(rect, 174.0)
    band.arcTo(rect, 174.0, -168.0)
    pen = QPen(HEADSET_LIGHT, 34.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(band)
    shine = QColor(acc)
    shine.setAlphaF(0.65 + 0.35 * beat)
    pen2 = QPen(shine, 7.0)
    pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen2)
    p.drawPath(band)
    for side in (-1, 1):
        x = cx + side * (rx - 4.0)
        k = 1.0 + 0.06 * beat
        cup = QRectF(x - 36.0 * k, 296.0 - 96.0 * k, 72.0 * k, 192.0 * k)
        halo = QColor(acc)
        halo.setAlphaF(0.10 + 0.18 * beat)
        p.setPen(QPen(halo, 18.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(cup, 32.0, 32.0)
        p.setPen(QPen(acc, 5.0))
        p.setBrush(HEADSET)
        p.drawRoundedRect(cup, 30.0, 30.0)
        pad = QColor(acc)
        pad.setAlphaF(0.30 + 0.25 * beat)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pad)
        p.drawRoundedRect(QRectF(x - 17.0, 296.0 - 60.0, 34.0, 120.0), 17.0, 17.0)


def _draw_equalizer(p, it: Item, theme, acc, frame) -> None:
    bars = it.data or (0.2,) * BAR_COUNT
    w, gap, base, hmax = 22.0, 12.0, 552.0, 100.0
    total = len(bars) * w + (len(bars) - 1) * gap
    x0 = CENTER_X - total / 2.0
    p.setPen(Qt.PenStyle.NoPen)
    for i, v in enumerate(bars):
        h = max(8.0, hmax * v)
        rect = QRectF(x0 + i * (w + gap), base - h, w, h)
        c = QColor(acc)
        c.setAlphaF(0.55 + 0.4 * v)
        p.setBrush(c)
        p.drawRoundedRect(rect, w / 2.0, w / 2.0)


def _draw_loading(p, it: Item, theme, acc, frame) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(3):
        k = max(0.0, math.sin(it.phase * 6.0 - i * 0.9))
        c = QColor(theme.eye_light)
        c.setAlphaF(0.45 + 0.55 * k)
        p.setBrush(c)
        p.drawEllipse(QPointF(CENTER_X - 78.0 + i * 78.0, 506.0 - 22.0 * k), 17.0, 17.0)


def _draw_question(p, it: Item, theme, acc, frame) -> None:
    _at(p, it.x, it.y, 52.0, it.rot)
    pen = QPen(theme.eye_light, 0.32)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    q = QPainterPath()
    q.moveTo(-0.55, -1.0)
    q.arcTo(QRectF(-0.55, -1.55, 1.1, 1.1), 180.0, -200.0)
    q.cubicTo(0.35, -0.35, 0.0, -0.3, 0.0, 0.05)
    p.drawPath(q)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.eye_light)
    p.drawEllipse(QPointF(0.0, 0.62), 0.19, 0.19)


def _draw_exclaim(p, it: Item, theme, acc, frame) -> None:
    _at(p, it.x, it.y, 52.0 * it.size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(AMBER)
    p.drawRoundedRect(QRectF(-0.2, -1.5, 0.4, 1.6), 0.2, 0.2)
    p.drawEllipse(QPointF(0.0, 0.5), 0.22, 0.22)


def _draw_sweat(p, it: Item, theme, acc, frame) -> None:
    _at(p, it.x, it.y, 20.0)
    _fill(p, _teardrop_path(), TEAR)


def _draw_battery(p, it: Item, theme, acc, frame) -> None:
    blink = 0.5 + 0.5 * math.sin(it.phase * 5.0)
    color = QColor(RED)
    p.translate(it.x, it.y)
    pen = QPen(color, 6.0)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(-48.0, -23.0, 92.0, 46.0), 9.0, 9.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(47.0, -9.0, 8.0, 18.0), 3.0, 3.0)
    fill = QColor(color)
    fill.setAlphaF(0.25 + 0.75 * blink)
    p.setBrush(fill)
    p.drawRoundedRect(QRectF(-41.0, -16.0, 18.0, 32.0), 4.0, 4.0)


def _draw_signal(p, it: Item, theme, acc, frame) -> None:
    p.translate(it.x, it.y)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(acc)
    p.drawEllipse(QPointF(0.0, 0.0), 8.0, 8.0)
    for k in range(3):
        a = max(0.0, math.sin(it.phase * 5.0 - k * 0.9))
        c = QColor(acc)
        c.setAlphaF(0.2 + 0.8 * a)
        pen = QPen(c, 8.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = 28.0 + 26.0 * k
        p.drawArc(QRectF(-r, -r, 2 * r, 2 * r), 45 * 16, 90 * 16)


_DRAWERS = {
    "note": _draw_note, "heart": _draw_heart, "zzz": _draw_zzz, "sparkle": _draw_sparkle,
    "tear": _draw_tear, "confetti": _draw_confetti,
    "eye_heart": _draw_eye_heart, "eye_star": _draw_eye_star, "eye_spiral": _draw_eye_spiral,
    "wink": _draw_wink, "blush": _draw_blush,
    "headphones": _draw_headphones, "equalizer": _draw_equalizer, "loading": _draw_loading,
    "question": _draw_question, "exclaim": _draw_exclaim, "sweat": _draw_sweat,
    "battery": _draw_battery, "signal": _draw_signal,
}
