"""Icone na bandeja do sistema (opcional).

Alguns desktops nao mostram bandeja (GNOME precisa da extensao "AppIndicator"). Se nao houver,
o programa segue normal: use os atalhos de teclado ou `aris-eyes.sh --send ...`.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

log = logging.getLogger("aris_eyes.tray")


def make_icon(eye_color: str = "#2f9bff") -> QIcon:
    """Rostinho desenhado em codigo (sem arquivos de imagem)."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#05080f"))
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setBrush(QColor(eye_color))
    p.drawRoundedRect(14, 17, 15, 30, 7, 7)
    p.drawRoundedRect(35, 17, 15, 30, 7, 7)
    p.end()
    return QIcon(pixmap)


def install_tray(icon: QIcon, *, on_toggle_hidden: Callable[[], None], on_fullscreen: Callable[[], None],
                 on_mini: Callable[[], None], on_quit: Callable[[], None]) -> Optional[QSystemTrayIcon]:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.info("sem bandeja de sistema neste desktop; seguindo sem icone")
        return None
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("ARIS")
    menu = QMenu()
    menu.addAction("Mostrar / esconder", on_toggle_hidden)
    menu.addAction("Tela cheia", on_fullscreen)
    menu.addAction("Miniatura", on_mini)
    menu.addSeparator()
    menu.addAction("Sair", on_quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: on_toggle_hidden()
                           if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray._menu = menu                         # mantem o menu vivo
    tray.show()
    return tray
