"""API de comandos dos olhos. E a "porta de entrada" para a ARIS e para os atalhos do desktop.

Cada comando e uma linha de texto; a resposta e "ok", um valor, ou "erro: ...".
"""
from __future__ import annotations

from typing import Callable

from .eyes.presets import MOOD_ORDER, parse_mood
from .modes import DisplayController, Mode, parse_mode
from .ui.eyes_widget import EyesWidget

HELP = """comandos:
  fullscreen | mini | hide | show      muda o modo (show = volta ao ultimo modo visivel)
  toggle                               tela cheia <-> miniatura
  cycle                                tela cheia -> miniatura -> escondida -> tela cheia
  mood <nome> | state <nome>           expressao: """ + ", ".join(m.value for m in MOOD_ORDER) + """
  look <x> <y> [segundos]              olha para (x, y) entre -1 e 1; 'look center' volta
  speech <0..1|off>                    volume da fala (anima os olhos ao falar); off = simulado
  blink                                pisca agora
  top on|off                           miniatura sempre no topo (X11)
  status | ping | help | quit"""


class EyesAPI:
    def __init__(self, eyes: EyesWidget, controller: DisplayController, config,
                 quit_callback: Callable[[], None]):
        self._eyes = eyes
        self._display = controller
        self._cfg = config
        self._quit = quit_callback

    # ------------------------------------------------------------------ operacoes diretas
    def set_mood(self, name: str) -> bool:
        mood = parse_mood(name)
        if mood is None:
            return False
        self._eyes.set_mood(mood)
        return True

    def set_always_on_top(self, value: bool) -> None:
        self._cfg.always_on_top = bool(value)
        if self._display.mode is Mode.MINI:
            self._display.refresh()

    # ------------------------------------------------------------------ texto -> acao
    def execute(self, line: str) -> str:
        parts = line.strip().split()
        if not parts:
            return "erro: comando vazio"
        cmd, args = parts[0].lower(), parts[1:]
        d = self._display

        if cmd == "ping":
            return "pong"
        if cmd == "help":
            return HELP
        if cmd == "status":
            mode = d.mode.value if d.mode else "none"
            return f"mode={mode} mood={self._eyes.current_mood().value}"
        if cmd in ("fullscreen", "mini", "hide", "hidden"):
            d.set_mode(parse_mode(cmd))
            return "ok"
        if cmd == "show":
            d.show()
            return "ok"
        if cmd == "toggle":
            d.toggle_fullscreen()
            return "ok"
        if cmd == "cycle":
            d.cycle()
            return "ok"
        if cmd == "mode" and args:
            mode = parse_mode(args[0])
            if mode is None:
                return "erro: modo desconhecido (fullscreen, mini, hidden)"
            d.set_mode(mode)
            return "ok"
        if cmd in ("mood", "state"):
            if not args:
                return "erro: use: mood <nome>"
            return "ok" if self.set_mood(args[0]) else "erro: expressao desconhecida: " + args[0]
        if cmd == "look":
            return self._look(args)
        if cmd == "speech":
            return self._speech(args)
        if cmd == "blink":
            self._eyes.animator.blink_now()
            return "ok"
        if cmd == "top":
            if not args or args[0].lower() not in ("on", "off"):
                return "erro: use: top on|off"
            self.set_always_on_top(args[0].lower() == "on")
            return "ok"
        if cmd == "quit":
            self._quit()
            return "ok"
        # atalho: "thinking" sozinho tambem funciona como expressao
        if not args and self.set_mood(cmd):
            return "ok"
        return "erro: comando desconhecido: " + cmd

    def _look(self, args: list[str]) -> str:
        if args and args[0].lower() == "center":
            self._eyes.animator.look_at(0.0, 0.0, 0.0)
            return "ok"
        try:
            x, y = float(args[0]), float(args[1])
            hold = float(args[2]) if len(args) > 2 else 1.5
        except (IndexError, ValueError):
            return "erro: use: look <x> <y> [segundos]"
        self._eyes.animator.look_at(x, y, hold)
        return "ok"

    def _speech(self, args: list[str]) -> str:
        if not args:
            return "erro: use: speech <0..1|off>"
        if args[0].lower() == "off":
            self._eyes.animator.set_speech_level(None)
            return "ok"
        try:
            self._eyes.animator.set_speech_level(float(args[0]))
        except ValueError:
            return "erro: use: speech <0..1|off>"
        return "ok"
