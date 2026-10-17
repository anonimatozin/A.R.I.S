"""Controle dos modos de exibicao. Nao conhece Qt: conversa com qualquer "janela" que tenha
present_fullscreen(), present_mini() e present_hidden() (facil de testar com uma janela falsa).
"""
from __future__ import annotations

from enum import Enum
from typing import Callable, Optional, Protocol


class Mode(str, Enum):
    FULLSCREEN = "fullscreen"
    MINI = "mini"
    HIDDEN = "hidden"


class Presentable(Protocol):
    def present_fullscreen(self) -> None: ...
    def present_mini(self) -> None: ...
    def present_hidden(self) -> None: ...


def parse_mode(name: str) -> Optional[Mode]:
    key = (name or "").strip().lower()
    key = {"hide": "hidden", "escondida": "hidden", "esconder": "hidden", "miniatura": "mini",
           "tela-cheia": "fullscreen", "cheia": "fullscreen"}.get(key, key)
    try:
        return Mode(key)
    except ValueError:
        return None


class DisplayController:
    def __init__(self, window: Presentable, on_change: Optional[Callable[[Mode], None]] = None):
        self._window = window
        self._on_change = on_change
        self._mode: Optional[Mode] = None
        self._last_visible = Mode.FULLSCREEN

    @property
    def mode(self) -> Optional[Mode]:
        return self._mode

    def set_mode(self, mode: Mode) -> None:
        if mode is self._mode:
            return
        if mode is Mode.FULLSCREEN:
            self._window.present_fullscreen()
        elif mode is Mode.MINI:
            self._window.present_mini()
        else:
            self._window.present_hidden()
        if mode is not Mode.HIDDEN:
            self._last_visible = mode
        self._mode = mode
        if self._on_change:
            self._on_change(mode)

    def refresh(self) -> None:
        """Reaplica o modo atual (ex.: depois de mudar 'sempre no topo')."""
        mode, self._mode = self._mode, None
        if mode is not None:
            self.set_mode(mode)

    def show(self) -> None:
        """Traz a interface de volta, no ultimo modo visivel."""
        if self._mode is None or self._mode is Mode.HIDDEN:
            self.set_mode(self._last_visible)

    def toggle_fullscreen(self) -> None:
        self.set_mode(Mode.MINI if self._mode is Mode.FULLSCREEN else Mode.FULLSCREEN)

    def toggle_hidden(self) -> None:
        if self._mode is Mode.HIDDEN:
            self.show()
        else:
            self.set_mode(Mode.HIDDEN)

    def cycle(self) -> None:
        order = {Mode.FULLSCREEN: Mode.MINI, Mode.MINI: Mode.HIDDEN, Mode.HIDDEN: Mode.FULLSCREEN}
        self.set_mode(order.get(self._mode, Mode.FULLSCREEN))
