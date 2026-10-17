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
}


def parse_mood(name: str) -> Optional[Mood]:
    key = (name or "").strip().lower()
    key = ALIASES.get(key, key)
    try:
        return Mood(key)
    except ValueError:
        return None


MOOD_ORDER = tuple(Mood)
