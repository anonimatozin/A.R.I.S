"""Expressoes dos olhos. Para criar uma nova, adicione um Mood e um Preset aqui (nada mais muda).

Coordenadas num "espaco de desenho" de 1000 x 560 unidades; o renderer ajusta ao tamanho da janela.
Parametros animados (cada um segue uma mola ate o valor da expressao):
  w, h        largura e altura de cada olho
  round       arredondamento (0 = retangulo, 1 = pilula)
  gap         distancia entre os olhos
  open        abertura geral (1 = normal; piscar e dormir reduzem)
  lid_top     quanto da parte de cima fica coberta por palpebra (0..1)
  lid_slant   inclinacao da palpebra: >0 bravo (canto interno baixo), <0 triste (canto externo baixo)
  lid_bottom  "bochecha" que sobe e deixa o olho em arco ^ (feliz)
  glow        brilho em volta dos olhos
  x_mix       0..1 transforma os olhos em X (erro)
  asym        diferenca entre os olhos (pensando: um olho estreita)
  dy          desloca os olhos para baixo/cima

Alem da forma dos olhos, cada humor pode ligar "props" (fone, notas, coracoes, zzz...), desenhados por
eyes/props.py + eyes/props_renderer.py. Veja MOOD_PROPS no fim deste arquivo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Mood(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    SLEEPY = "sleepy"
    THINKING = "thinking"
    LISTENING = "listening"
    SPEAKING = "speaking"
    ERROR = "error"
    SLEEPING = "sleeping"
    ALERT = "alert"
    # --- novos (v2) ---
    LOVE = "love"
    WINK = "wink"
    FOCUSED = "focused"
    CURIOUS = "curious"
    PROUD = "proud"
    SHY = "shy"
    SUSPICIOUS = "suspicious"
    EXCITED = "excited"
    TIRED = "tired"
    MUSIC = "music"
    CHILL = "chill"
    LOADING = "loading"
    DIZZY = "dizzy"
    CRYING = "crying"


BASE = {
    "w": 280.0, "h": 340.0, "round": 0.62, "gap": 120.0, "open": 1.0,
    "lid_top": 0.0, "lid_slant": 0.0, "lid_bottom": 0.0,
    "glow": 1.0, "x_mix": 0.0, "asym": 0.0, "dy": 0.0,
}
PARAMS = tuple(BASE)


@dataclass(frozen=True, eq=False)
class Preset:
    params: dict = field(default_factory=dict)   # so o que difere do BASE
    gaze: tuple = (0.0, 0.0)    # para onde os olhos "descansam" (-1..1)
    wander: float = 1.0         # quanto olham em volta sozinhos (0 = olhar fixo)
    blink: float = 1.0          # frequencia de piscadas (0 = nao pisca)
    pulse: float = 0.0          # pulsar ao falar
    breathe: float = 1.0        # respiracao
    jitter: float = 0.0         # tremida/falha (erro)
    flash: float = 0.0          # brilho pulsando (alerta)

    def target(self, name: str) -> float:
        return float(self.params.get(name, BASE[name]))


PRESETS: dict[Mood, Preset] = {
    Mood.NEUTRAL: Preset(),
    Mood.HAPPY: Preset({"h": 300, "lid_bottom": 0.58, "glow": 1.15}, wander=0.5, blink=0.4, breathe=2.2),
    Mood.SAD: Preset({"h": 320, "lid_top": 0.22, "lid_slant": -0.9, "glow": 0.75, "dy": 14},
                     gaze=(0.0, 0.4), wander=0.25, blink=0.7, breathe=0.7),
    Mood.ANGRY: Preset({"w": 290, "h": 300, "lid_top": 0.2, "lid_slant": 1.0, "glow": 1.25},
                       wander=0.15, blink=0.35, breathe=0.5),
    Mood.SURPRISED: Preset({"w": 300, "h": 390, "round": 0.75, "glow": 1.35, "open": 1.05},
                           wander=0.1, blink=0.15),
    Mood.SLEEPY: Preset({"lid_top": 0.48, "lid_slant": -0.25, "glow": 0.6, "dy": 10},
                        gaze=(0.0, 0.25), wander=0.25, blink=1.6, breathe=1.4),
    Mood.THINKING: Preset({"lid_top": 0.1, "lid_slant": 0.35, "asym": 0.7},
                          gaze=(-0.6, -0.65), wander=0.45, blink=0.7),
    Mood.LISTENING: Preset({"w": 295, "h": 375, "glow": 1.4, "open": 1.04}, wander=0.2, blink=0.8),
    Mood.SPEAKING: Preset({"glow": 1.2}, wander=0.7, pulse=1.0, breathe=0.5),
    Mood.ERROR: Preset({"x_mix": 1.0, "glow": 1.1}, wander=0.0, blink=0.0, jitter=1.0),
    Mood.SLEEPING: Preset({"open": 0.05, "glow": 0.45, "dy": 20}, wander=0.0, blink=0.0, breathe=2.5),
    Mood.ALERT: Preset({"w": 300, "h": 385, "glow": 1.6, "open": 1.05}, wander=0.1, blink=0.2, flash=1.0),
    # --- novos (v2) ---
    # apaixonado: o olho vira coracao (prop eye_heart), entao so o tamanho/brilho importam
    Mood.LOVE: Preset({"w": 250, "h": 250, "round": 1.0, "gap": 150, "glow": 0.35},
                      wander=0.1, blink=0.0, breathe=2.0),
    # piscadinha: carinha feliz + o olho direito vira "^" por um instante (prop wink)
    Mood.WINK: Preset({"h": 300, "lid_bottom": 0.5, "glow": 1.15}, wander=0.4, blink=0.3, breathe=2.0),
    Mood.FOCUSED: Preset({"h": 260, "lid_top": 0.3, "lid_slant": 0.15, "glow": 1.1},
                         wander=0.04, blink=0.25, breathe=0.6),
    Mood.CURIOUS: Preset({"h": 380, "round": 0.7, "asym": 0.45}, gaze=(0.55, -0.4), wander=0.55, blink=0.6),
    Mood.PROUD: Preset({"h": 300, "lid_top": 0.32, "lid_bottom": 0.22, "glow": 1.2},
                       gaze=(0.0, -0.45), wander=0.15, blink=0.35, breathe=1.6),
    Mood.SHY: Preset({"h": 300, "lid_top": 0.16, "lid_slant": -0.55, "lid_bottom": 0.2, "glow": 0.85, "dy": 8},
                     gaze=(-0.7, 0.5), wander=0.12, blink=1.2),
    Mood.SUSPICIOUS: Preset({"w": 330, "h": 200, "lid_top": 0.4, "lid_slant": 0.3, "glow": 0.95},
                            gaze=(0.8, 0.0), wander=0.08, blink=0.3, breathe=0.5),
    Mood.EXCITED: Preset({"w": 305, "h": 385, "round": 0.7, "lid_bottom": 0.3, "glow": 1.5, "open": 1.04},
                         wander=0.9, blink=0.5, breathe=2.6, pulse=0.5),
    Mood.TIRED: Preset({"lid_top": 0.5, "lid_slant": -0.2, "open": 0.7, "glow": 0.55, "dy": 14},
                       gaze=(0.0, 0.3), wander=0.15, blink=2.0, breathe=3.0),
    # musica: olhos sorrindo que pulsam no ritmo (o ritmo vem de PropEngine.beat -> set_speech_level)
    Mood.MUSIC: Preset({"h": 315, "lid_bottom": 0.3, "glow": 1.3}, wander=0.25, blink=0.5, breathe=1.2, pulse=0.8),
    Mood.CHILL: Preset({"h": 300, "lid_top": 0.2, "lid_slant": -0.15, "lid_bottom": 0.18, "glow": 1.0},
                       gaze=(0.0, 0.1), wander=0.15, blink=0.5, breathe=1.8, pulse=0.35),
    Mood.LOADING: Preset({"w": 200, "h": 200, "round": 1.0, "gap": 170, "glow": 1.1, "dy": -30},
                         wander=0.2, blink=0.6),
    # tonto: olhos redondos + espiral girando (prop eye_spiral)
    Mood.DIZZY: Preset({"w": 250, "h": 250, "round": 1.0, "gap": 140, "glow": 0.9},
                       wander=0.0, blink=0.0, jitter=0.3),
    Mood.CRYING: Preset({"h": 320, "lid_top": 0.24, "lid_slant": -1.0, "glow": 0.7, "dy": 16},
                        gaze=(0.0, 0.4), wander=0.12, blink=0.8, breathe=1.2, jitter=0.12),
}

# Props ligados por padrao a cada humor (ver eyes/props.py para a lista de props).
MOOD_PROPS: dict[Mood, tuple[str, ...]] = {
    Mood.SLEEPING: ("zzz",),
    Mood.ALERT: ("exclaim",),
    Mood.LOVE: ("eye_heart", "hearts"),
    Mood.WINK: ("wink",),
    Mood.CURIOUS: ("question",),
    Mood.PROUD: ("sparkles",),
    Mood.SHY: ("blush",),
    Mood.EXCITED: ("sparkles",),
    Mood.TIRED: ("zzz",),
    Mood.MUSIC: ("notes", "equalizer"),
    Mood.CHILL: ("headphones", "notes"),
    Mood.LOADING: ("loading",),
    Mood.DIZZY: ("eye_spiral",),
    Mood.CRYING: ("tears",),
}

# nomes alternativos (estados que a ARIS ja usa, em portugues e ingles)
ALIASES = {
    "idle": "neutral", "normal": "neutral", "neutro": "neutral", "ocioso": "neutral",
    "feliz": "happy", "alegre": "happy", "triste": "sad", "bravo": "angry", "raiva": "angry",
    "surpreso": "surprised", "surpresa": "surprised", "sono": "sleepy", "sonolento": "sleepy",
    "pensando": "thinking", "pensar": "thinking", "think": "thinking", "processing": "thinking",
    "working": "thinking", "executando": "thinking",
    "ouvindo": "listening", "listen": "listening", "escutando": "listening",
    "falando": "speaking", "speak": "speaking", "talking": "speaking",
    "erro": "error", "falha": "error",
    "dormindo": "sleeping", "dormir": "sleeping", "sleep": "sleeping",
    "alerta": "alert", "atencao": "alert",
    # --- novos (v2) ---
    "apaixonado": "love", "amor": "love", "coracao": "love", "paixao": "love",
    "piscadinha": "wink", "piscada": "wink", "pisca": "wink",
    "concentrado": "focused", "foco": "focused", "focus": "focused",
    "curioso": "curious", "curiosidade": "curious",
    "orgulhoso": "proud", "orgulho": "proud",
    "timido": "shy", "envergonhado": "shy", "vergonha": "shy",
    "desconfiado": "suspicious", "suspeito": "suspicious", "desconfiança": "suspicious",
    "animado": "excited", "empolgado": "excited", "euforico": "excited",
    "cansado": "tired", "cansaco": "tired",
    "musica": "music", "spotify": "music", "tocando": "music", "dancando": "music",
    "relaxado": "chill", "relax": "chill", "fone": "chill", "headphones": "chill",
    "carregando": "loading", "loading": "loading", "aguarde": "loading",
    "tonto": "dizzy", "zonzo": "dizzy", "tontura": "dizzy",
    "chorando": "crying", "choro": "crying", "chorar": "crying", "cry": "crying",
}


def parse_mood(name: str) -> Optional[Mood]:
    key = (name or "").strip().lower()
    key = ALIASES.get(key, key)
    try:
        return Mood(key)
    except ValueError:
        return None


MOOD_ORDER = tuple(Mood)
