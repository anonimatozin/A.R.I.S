"""Cenas: combinacoes prontas de humor + props (ex.: "spotify" = olhos no ritmo + notas + equalizador).

Uma cena e so dados (``SCENES``). O ``SceneController`` aplica a cena no animator + PropEngine, cuida do
tempo de duracao e, ao acabar (ou ao ``stop``), volta ao humor que estava antes. Sem Qt: testavel sem tela.

Uso tipico (o widget cria um controller e o chama a cada quadro)::

    scenes = SceneController(animator, engine)
    scenes.play("spotify")              # fica ate alguem chamar scenes.stop() ou mudar o humor
    scenes.play("comemorar", 4.0)       # dura 4 s e volta ao humor anterior
    scenes.update(dt)                   # a cada quadro
    scenes.set_mood(Mood.THINKING)      # mudar o humor encerra a cena (e liga os props do humor)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .presets import MOOD_PROPS, Mood
from .props import PropEngine


@dataclass(frozen=True)
class Scene:
    mood: Mood
    props: tuple = ()
    seconds: Optional[float] = None      # duracao padrao (None = ate mandarem parar)
    accent: Optional[str] = None         # cor de destaque de notas/fone/equalizador/ondas (hex)
    beat: bool = False                   # True = os olhos pulsam no ritmo (engine.beat)


SPOTIFY_GREEN = "#1ed760"

SCENES: dict[str, Scene] = {
    # --- musica ---
    "spotify": Scene(Mood.MUSIC, ("notes", "equalizer"), None, SPOTIFY_GREEN, beat=True),
    "fone": Scene(Mood.CHILL, ("headphones", "notes"), None, None, beat=True),
    "dancar": Scene(Mood.EXCITED, ("notes", "sparkles"), None, "#ff9de2", beat=True),
    # --- sentimentos ---
    "apaixonado": Scene(Mood.LOVE, ("eye_heart", "hearts"), 6.0),
    "piscadinha": Scene(Mood.WINK, ("wink",), 2.0),
    "timido": Scene(Mood.SHY, ("blush",), 6.0),
    "chorando": Scene(Mood.CRYING, ("tears",), 8.0),
    "orgulhoso": Scene(Mood.PROUD, ("sparkles",), 5.0),
    "comemorar": Scene(Mood.EXCITED, ("confetti", "sparkles", "eye_star"), 4.0),
    "tonto": Scene(Mood.DIZZY, ("eye_spiral",), 4.0),
    "nervoso": Scene(Mood.SUSPICIOUS, ("sweat",), 5.0),
    # --- sistema ---
    "carregando": Scene(Mood.LOADING, ("loading",)),
    "conectado": Scene(Mood.HAPPY, ("signal",), 2.8),
    "bateria": Scene(Mood.SAD, ("battery",)),
    "dormir": Scene(Mood.SLEEPING, ("zzz",)),
    "sono": Scene(Mood.TIRED, ("zzz",), 8.0),
    "curioso": Scene(Mood.CURIOUS, ("question",), 6.0),
    "alerta": Scene(Mood.ALERT, ("exclaim",), 4.0),
}

SCENE_ALIASES = {
    "musica": "spotify", "music": "spotify", "tocando": "spotify",
    "headphones": "fone", "ouvindo-musica": "fone", "chill": "fone",
    "love": "apaixonado", "amor": "apaixonado", "wink": "piscadinha",
    "shy": "timido", "envergonhado": "timido", "cry": "chorando", "crying": "chorando",
    "proud": "orgulhoso", "celebrate": "comemorar", "festa": "comemorar", "party": "comemorar",
    "dizzy": "tonto", "nervous": "nervoso", "loading": "carregando", "connected": "conectado",
    "battery": "bateria", "bateria-fraca": "bateria", "sleep": "dormir", "tired": "sono",
    "cansado": "sono", "curious": "curioso", "alert": "alerta", "dance": "dancar",
}


def resolve_scene(name: str) -> Optional[Scene]:
    key = (name or "").strip().lower()
    key = SCENE_ALIASES.get(key, key)
    return SCENES.get(key)


def scene_names() -> tuple:
    return tuple(SCENES)


class SceneController:
    """Liga cenas ao animator (olhos) e ao PropEngine (enfeites). Duck-typed: so usa
    ``animator.mood``, ``animator.set_mood`` e ``animator.set_speech_level``."""

    def __init__(self, animator, engine: PropEngine):
        self.animator = animator
        self.engine = engine
        self.accent: Optional[str] = None         # cor de destaque atual (None = do tema)
        self.current: Optional[str] = None        # nome da cena em andamento
        self._saved_mood: Optional[Mood] = None
        self._left: Optional[float] = None
        self._feeding_beat = False

    # ------------------------------------------------------------------ comandos
    def play(self, name: str, seconds: Optional[float] = None) -> bool:
        scene = resolve_scene(name)
        if scene is None:
            return False
        if self.current is None:
            self._saved_mood = self.animator.mood
        self.current = (name or "").strip().lower()
        self.engine.clear()
        self.animator.set_mood(scene.mood)
        for prop in scene.props:
            self.engine.add(prop)
        self.accent = scene.accent
        duration = seconds if seconds is not None else scene.seconds
        self._left = float(duration) if duration and duration > 0 else None
        self._set_beat_feed(scene.beat)
        return True

    def stop(self, restore: bool = True) -> None:
        """Encerra a cena. ``restore`` volta ao humor anterior e religa os props dele."""
        if self.current is None:
            return
        self.engine.clear()
        self.current = None
        self.accent = None
        self._left = None
        self._set_beat_feed(False)
        if restore and self._saved_mood is not None:
            self.animator.set_mood(self._saved_mood)
            self.engine.sync_mood(MOOD_PROPS.get(self._saved_mood, ()))
        self._saved_mood = None

    def set_mood(self, mood: Mood) -> None:
        """Ponto unico para trocar de humor: encerra a cena atual e liga os props do novo humor."""
        if self.current is not None:
            self.stop(restore=False)
        self.animator.set_mood(mood)
        self.engine.sync_mood(MOOD_PROPS.get(mood, ()))

    def set_accent(self, color: Optional[str]) -> None:
        self.accent = color or None

    # ------------------------------------------------------------------ quadro a quadro
    def update(self, dt: float) -> None:
        if self._left is not None:
            self._left -= dt
            if self._left <= 0.0:
                self.stop()
        if self._feeding_beat:
            self.animator.set_speech_level(self.engine.beat)

    def _set_beat_feed(self, on: bool) -> None:
        if self._feeding_beat and not on:
            self.animator.set_speech_level(None)
        self._feeding_beat = on
