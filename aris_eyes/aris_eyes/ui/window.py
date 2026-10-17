"""Janela unica dos olhos. Sabe APRESENTAR-se em tres formas (tela cheia, miniatura, escondida);
quem decide qual forma usar e o DisplayController (modes.py).

Diferencas entre ambientes graficos (veja o README):
  X11      : posicao, "sempre no topo" e canto da tela funcionam.
  Wayland  : o compositor decide a posicao e ignora "sempre no topo" para janelas comuns.
             Arrastar funciona via startSystemMove() (o proprio compositor move a janela).
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from ..config import Config
from ..eyes.presets import MOOD_ORDER
from .eyes_widget import EyesWidget

log = logging.getLogger("aris_eyes.window")

MINI_MIN_W, MINI_MAX_W = 160, 720


class EyesWindow(QWidget):
    mode_requested = Signal(str)            # "fullscreen" | "mini" | "hidden"
    quit_requested = Signal()
    always_on_top_requested = Signal(bool)
    mood_requested = Signal(str)

    def __init__(self, config: Config):
        super().__init__()
        self.cfg = config
        self.shown_mode = "hidden"
        self.setWindowTitle("ARIS")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.eyes = EyesWidget(config, self)
        layout.addWidget(self.eyes)

        self._drag_offset: Optional[QPoint] = None
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.timeout.connect(self._hide_cursor)

        self.eyes.press_started.connect(self._on_press)
        self.eyes.dragged.connect(self._on_drag)
        self.eyes.double_clicked.connect(self._on_double_click)
        self.eyes.wheel_scrolled.connect(self._on_wheel)
        self.eyes.menu_requested.connect(self._show_menu)
        self.eyes.activity.connect(self._on_activity)

    # ------------------------------------------------------------------ ambiente
    @staticmethod
    def is_wayland() -> bool:
        return QGuiApplication.platformName().startswith("wayland")

    def _target_screen(self) -> QScreen:
        screens = QGuiApplication.screens()
        if 0 <= self.cfg.screen < len(screens):
            return screens[self.cfg.screen]
        return self.screen() or QGuiApplication.primaryScreen()

    # ------------------------------------------------------------------ as tres formas
    def present_fullscreen(self) -> None:
        self._remember_position()
        self.hide()
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.eyes.mini_style = False
        self.setMinimumSize(0, 0)
        self._assign_screen(self._target_screen())
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
        self.shown_mode = "fullscreen"
        self.eyes.start(self.cfg.fps_fullscreen)
        self._arm_cursor_hide()

    def present_mini(self) -> None:
        self._cursor_timer.stop()
        self.unsetCursor()
        if self.shown_mode != "mini":
            self._remember_position()
        self.hide()
        kind = Qt.WindowType.Tool if self.cfg.skip_taskbar else Qt.WindowType.Window
        flags = kind | Qt.WindowType.FramelessWindowHint
        if self.cfg.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)   # nao rouba o foco
        self.eyes.mini_style = True
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.setMinimumSize(MINI_MIN_W, 70)
        self.resize(self.cfg.mini_width, self.cfg.mini_height)
        self._place_mini()
        self.show()
        self.shown_mode = "mini"
        self.eyes.start(self.cfg.fps_mini)

    def present_hidden(self) -> None:
        self._remember_position()
        self.eyes.stop()                      # escondida nao gasta CPU
        self._cursor_timer.stop()
        self.hide()
        self.shown_mode = "hidden"

    # ------------------------------------------------------------------ posicao (so X11)
    def _assign_screen(self, screen: QScreen) -> None:
        try:
            if hasattr(self, "setScreen"):
                self.setScreen(screen)
            else:
                self.winId()                  # cria o handle nativo
                handle = self.windowHandle()
                if handle is not None:
                    handle.setScreen(screen)
        except Exception as exc:              # nunca deixar a escolha de monitor derrubar a janela
            log.debug("nao consegui escolher o monitor: %s", exc)

    def _place_mini(self) -> None:
        if self.is_wayland():
            return                            # Wayland: o compositor escolhe a posicao
        pos = self.cfg.mini_position
        if pos:
            point = QPoint(pos[0], pos[1])
            if any(s.geometry().adjusted(-40, -40, 40, 40).contains(point) for s in QGuiApplication.screens()):
                self.move(point)
                return
        geo = self._target_screen().availableGeometry()
        m, w, h = self.cfg.mini_margin, self.width(), self.height()
        corner = self.cfg.mini_corner
        x = geo.left() + m if corner.endswith("left") else geo.right() - w - m + 1
        y = geo.top() + m if corner.startswith("top") else geo.bottom() - h - m + 1
        self.move(x, y)

    def _remember_position(self) -> None:
        if self.shown_mode == "mini" and not self.is_wayland():
            self.cfg.mini_position = [self.x(), self.y()]

    # ------------------------------------------------------------------ mouse
    def _on_press(self, global_pos: QPoint) -> None:
        if self.shown_mode != "mini":
            return
        handle = self.windowHandle()
        if handle is not None and hasattr(handle, "startSystemMove") and handle.startSystemMove():
            return                            # o sistema cuida de arrastar (funciona no Wayland)
        self._drag_offset = global_pos - self.frameGeometry().topLeft()   # plano B manual (X11)

    def _on_drag(self, global_pos: QPoint) -> None:
        if self.shown_mode == "mini" and self._drag_offset is not None and not self.is_wayland():
            self.move(global_pos - self._drag_offset)

    def _on_double_click(self) -> None:
        self.mode_requested.emit("mini" if self.shown_mode == "fullscreen" else "fullscreen")

    def _on_wheel(self, step: int) -> None:
        if self.shown_mode != "mini":
            return
        ratio = self.cfg.mini_height / self.cfg.mini_width
        width = int(self.width() * (1.08 if step > 0 else 1 / 1.08))
        width = max(MINI_MIN_W, min(MINI_MAX_W, width))
        self.cfg.mini_width, self.cfg.mini_height = width, int(width * ratio)
        self.resize(self.cfg.mini_width, self.cfg.mini_height)

    def _on_activity(self) -> None:
        if self.shown_mode == "fullscreen":
            self.unsetCursor()
            self._arm_cursor_hide()

    def _arm_cursor_hide(self) -> None:
        if self.cfg.hide_cursor_ms > 0:
            self._cursor_timer.start(self.cfg.hide_cursor_ms)

    def _hide_cursor(self) -> None:
        if self.shown_mode == "fullscreen":
            self.setCursor(Qt.CursorShape.BlankCursor)

    # ------------------------------------------------------------------ menu (botao direito)
    def _show_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("Tela cheia", lambda: self.mode_requested.emit("fullscreen"))
        menu.addAction("Miniatura", lambda: self.mode_requested.emit("mini"))
        menu.addAction("Esconder", lambda: self.mode_requested.emit("hidden"))
        menu.addSeparator()
        top = menu.addAction("Sempre no topo")
        top.setCheckable(True)
        top.setChecked(self.cfg.always_on_top)
        top.triggered.connect(self.always_on_top_requested.emit)
        moods = menu.addMenu("Expressao")
        for mood in MOOD_ORDER:
            moods.addAction(mood.value, lambda m=mood.value: self.mood_requested.emit(m))
        menu.addSeparator()
        menu.addAction("Sair", self.quit_requested.emit)
        menu.exec(global_pos)

    # ------------------------------------------------------------------ fechar pela janela
    def closeEvent(self, event) -> None:
        event.ignore()                        # fechar a janela so esconde; sair e explicito
        self.mode_requested.emit("hidden")
