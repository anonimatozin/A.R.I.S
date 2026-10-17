"""Atalhos de teclado a partir do config.json (secao "shortcuts").

Estes atalhos valem enquanto uma janela da ARIS estiver em foco. Para atalhos GLOBAIS (funcionam
com a interface escondida ou com outro programa em foco) use o atalho do seu desktop chamando
`aris-eyes.sh --send <comando>`; e a unica forma que funciona igual em X11 e Wayland (veja o README).
"""
from __future__ import annotations

import logging
from typing import Callable, Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

log = logging.getLogger("aris_eyes.shortcuts")


def install_shortcuts(parent: QWidget, bindings: Mapping[str, str],
                      actions: Mapping[str, Callable[[], None]],
                      mood_names: list[str], on_mood: Callable[[str], None],
                      dev_keys: bool) -> list[QShortcut]:
    created: list[QShortcut] = []

    def add(sequence: str, fn: Callable[[], None]) -> None:
        keys = QKeySequence(sequence)
        if keys.isEmpty():
            log.warning("atalho invalido ignorado: %r", sequence)
            return
        shortcut = QShortcut(keys, parent)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.setAutoRepeat(False)
        shortcut.activated.connect(fn)
        created.append(shortcut)

    for action, sequence in bindings.items():
        if not sequence:
            continue                          # "" desativa o atalho
        fn = actions.get(action)
        if fn is None:
            log.warning("acao de atalho desconhecida: %r (validas: %s)", action, ", ".join(actions))
            continue
        add(sequence, fn)

    if dev_keys:                              # 1..9 e 0 trocam a expressao para voce testar
        for i, name in enumerate(mood_names[:10]):
            add(str((i + 1) % 10), lambda n=name: on_mood(n))
    return created
