"""API de comandos dos olhos. E a "porta de entrada" para a ARIS e para os atalhos do desktop.

Cada comando e uma linha de texto; a resposta e "ok", um valor, ou "erro: ...".
"""
from __future__ import annotations

from typing import Callable

from .eyes.presets import MOOD_ORDER, parse_mood
from .eyes.props import PROP_NAMES
from .eyes.scenes import scene_names
from .modes import DisplayController, Mode, parse_mode
from .ui.eyes_widget import EyesWidget

HELP = """comandos:
  fullscreen | mini | hide | show      muda o modo (show = volta ao ultimo modo visivel)
  toggle                               tela cheia <-> miniatura
  cycle                                tela cheia -> miniatura -> escondida -> tela cheia
  mood <nome> | state <nome>           expressao: """ + ", ".join(m.value for m in MOOD_ORDER) + """
  look <x> <y> [segundos]              olha para (x, y) entre -1 e 1; 'look center' volta
  speech <0..1|off>                    volume da fala (anima os olhos ao falar); off = simulado
  scene <nome> [segundos] | scene off  cena pronta (humor + enfeites): """ + ", ".join(scene_names()) + """
  prop <nome> on|off [segundos]        liga/desliga um enfeite: """ + ", ".join(PROP_NAMES) + """
  music <0..1|off>                     volume da musica (ritmo dos olhos/equalizador); off = batida simulada
  accent <#rrggbb|off>                 cor de destaque das notas/fone/equalizador (ex.: cor da capa)
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
            scene = self._eyes.scenes.current or "-"
            props = ",".join(sorted(self._eyes.props.active_names())) or "-"
            return f"mode={mode} mood={self._eyes.current_mood().value} scene={scene} props={props}"
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
        if cmd in ("scene", "prop", "music", "accent") and not getattr(self._eyes, "props_enabled", True):
            return "erro: enfeites/cenas desativados (props_enabled=false no config.json)"
        if cmd == "look":
            return self._look(args)
        if cmd == "speech":
            return self._speech(args)
        if cmd == "scene":
            return self._scene(args)
        if cmd == "prop":
            return self._prop(args)
        if cmd == "music":
            return self._music(args)
        if cmd == "accent":
            return self._accent(args)
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

    def _scene(self, args: list[str]) -> str:
        if not args:
            return "erro: use: scene <nome> [segundos] | scene off"
        if args[0].lower() in ("off", "stop", "parar"):
            self._eyes.scenes.stop()
            return "ok"
        try:
            seconds = float(args[1]) if len(args) > 1 else None
        except ValueError:
            return "erro: use: scene <nome> [segundos]"
        if not self._eyes.scenes.play(args[0], seconds):
            return "erro: cena desconhecida: " + args[0] + " (" + ", ".join(scene_names()) + ")"
        return "ok"

    def _prop(self, args: list[str]) -> str:
        if len(args) < 2 or args[1].lower() not in ("on", "off"):
            return "erro: use: prop <nome> on|off [segundos]"
        name, on = args[0].lower(), args[1].lower() == "on"
        if name not in PROP_NAMES:
            return "erro: enfeite desconhecido: " + name + " (" + ", ".join(PROP_NAMES) + ")"
        if not on:
            self._eyes.props.remove(name)
            return "ok"
        try:
            seconds = float(args[2]) if len(args) > 2 else None
        except ValueError:
            return "erro: use: prop <nome> on [segundos]"
        self._eyes.props.add(name, seconds)
        return "ok"

    def _music(self, args: list[str]) -> str:
        if not args:
            return "erro: use: music <0..1|off>"
        if args[0].lower() == "off":
            self._eyes.props.set_level(None)
            return "ok"
        try:
            self._eyes.props.set_level(float(args[0]))
        except ValueError:
            return "erro: use: music <0..1|off>"
        return "ok"

    def _accent(self, args: list[str]) -> str:
        if not args:
            return "erro: use: accent <#rrggbb|off>"
        if args[0].lower() in ("off", "reset"):
            self._eyes.scenes.set_accent(None)
            return "ok"
        color = args[0] if args[0].startswith("#") else "#" + args[0]
        if len(color) != 7 or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
            return "erro: cor invalida (use #rrggbb)"
        self._eyes.scenes.set_accent(color)
        return "ok"
