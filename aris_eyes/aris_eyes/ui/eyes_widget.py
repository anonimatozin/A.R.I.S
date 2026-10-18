"""Widget dos olhos: roda o animator num timer e pinta com o renderer.

Nao decide nada sobre janela/modo: so avisa (sinais) quando o usuario clica, arrasta, gira a
rodinha ou pede o menu. Quem reage a isso e a EyesWindow.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QElapsedTimer, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..config import Config
from ..eyes.animator import EyeAnimator, Frame, IdleSettings
from ..eyes.presets import Mood, parse_mood
from ..eyes.props import PropEngine
from ..eyes.props_renderer import draw_props
from ..eyes.renderer import Theme, draw_eyes
from ..eyes.scenes import SceneController


# Diferenca minima (por campo) para valer a pena repintar: ~0,25 unidade de desenho = menos de 1 pixel.
# Assim, com os olhos parados (so respirando), o programa repinta bem menos e gasta pouca CPU.
_EPS = {"w": 0.25, "h": 0.25, "gap": 0.25, "dy": 0.25, "round": 0.001, "open": 0.0007,
        "lid_top": 0.0007, "lid_slant": 0.001, "lid_bottom": 0.0007, "glow": 0.01,
        "x_mix": 0.003, "asym": 0.002, "gx": 0.003, "gy": 0.005}


def frames_differ(a: Frame, b: Frame) -> bool:
    return any(abs(getattr(a, name) - getattr(b, name)) > eps for name, eps in _EPS.items())


class EyesWidget(QWidget):
    press_started = Signal(QPoint)      # botao esquerdo apertado (posicao global)
    dragged = Signal(QPoint)            # arrastando com o botao esquerdo (posicao global)
    double_clicked = Signal()
    wheel_scrolled = Signal(int)        # +1 / -1
    menu_requested = Signal(QPoint)     # botao direito (posicao global)
    activity = Signal()                 # mouse mexeu

    def __init__(self, config: Config, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.cfg = config
        self.theme = Theme.from_config(config)
        self.mini_style = False         # True = desenha o "rostinho" arredondado da miniatura
        idle = IdleSettings(config.blink_min_s, config.blink_max_s, config.saccades, config.breathing)
        self.animator = EyeAnimator(idle, parse_mood(config.initial_mood) or Mood.NEUTRAL)
        self.props = PropEngine()                 # enfeites (fone, notas, coracoes...)
        self.scenes = SceneController(self.animator, self.props)
        self.props_enabled = bool(config.props_enabled)  # kill-switch: False = olhos como antes
        if self.props_enabled:
            self.scenes.set_mood(self.animator.mood)  # liga os props do humor inicial
        self._frame = self.animator.update(0.0)
        self._pframe = self.props.update(0.0) if self.props_enabled else None
        self._painted: Optional[Frame] = None     # ultimo quadro realmente pintado
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)

    # ------------------------------------------------------------------ ciclo
    def start(self, fps: int) -> None:
        self._timer.start(max(1, round(1000 / max(1, fps))))
        self._clock.restart()

    def stop(self) -> None:
        self._timer.stop()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        dt = self._clock.restart() / 1000.0
        if self.props_enabled:
            self.scenes.update(dt)
        self._frame = self.animator.update(dt)
        if self.props_enabled:
            self._pframe = self.props.update(dt)
        animating = self.props_enabled and self.props.is_animating
        if self._painted is None or animating or frames_differ(self._frame, self._painted):
            self.update()

    # ------------------------------------------------------------------ atalhos para o animator
    def set_mood(self, mood: Mood) -> None:
        self.scenes.set_mood(mood)                # tambem encerra cena e troca os props do humor

    def current_mood(self) -> Mood:
        return self.animator.mood

    # ------------------------------------------------------------------ pintura
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        if self.mini_style:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(event.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            face = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
            radius = min(face.width(), face.height()) * 0.2
            p.setPen(QPen(self.theme.border, 2.0))
            p.setBrush(self.theme.background)
            p.drawRoundedRect(face, radius, radius)
            area = face.adjusted(face.width() * 0.04, face.height() * 0.04,
                                 -face.width() * 0.04, -face.height() * 0.04)
        else:
            p.fillRect(self.rect(), self.theme.background)
            area = QRectF(self.rect())
        draw_eyes(p, self._frame, self.theme, area)
        if self.props_enabled and self._pframe is not None:
            draw_props(p, self._pframe, self.theme, area, self._frame, self.scenes.accent)
        p.end()
        self._painted = self._frame

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.press_started.emit(ev.globalPosition().toPoint())
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        self.activity.emit()
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self.dragged.emit(ev.globalPosition().toPoint())
        super().mouseMoveEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()

    def wheelEvent(self, ev) -> None:
        delta = ev.angleDelta().y()
        if delta:
            self.wheel_scrolled.emit(1 if delta > 0 else -1)

    def contextMenuEvent(self, ev) -> None:
        self.menu_requested.emit(ev.globalPos())
