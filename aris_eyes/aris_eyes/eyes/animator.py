"""Sistema de animacao dos olhos. Matematica pura (sem Qt): facil de testar e de reaproveitar.

Ideia: cada parametro do olho segue uma MOLA ate o valor da expressao atual (transicoes suaves, com
um leve "boing" nas formas). Por cima disso rodam comportamentos de vida:
piscadas (as vezes duplas), olhadas aleatorias, respiracao, pulsar ao falar, tremida no erro.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

from .presets import BASE, PARAMS, PRESETS, Mood

MAX_SUBSTEP = 1.0 / 120.0

# (rigidez, amortecimento): amortecimento < 1 deixa passar um pouco do alvo (efeito "vivo")
SPRING_TUNING = {
    "w": (110.0, 0.62), "h": (110.0, 0.62), "round": (100.0, 0.9), "gap": (100.0, 0.8),
    "open": (130.0, 0.7), "lid_top": (150.0, 0.7), "lid_slant": (150.0, 0.7),
    "lid_bottom": (130.0, 0.65), "glow": (50.0, 1.0), "x_mix": (70.0, 1.0),
    "asym": (90.0, 0.8), "dy": (90.0, 0.8),
}


class Spring:
    """Mola amortecida integrada em passos pequenos (estavel mesmo se um quadro demorar)."""
    __slots__ = ("x", "v", "target", "k", "c")

    def __init__(self, value: float, stiffness: float = 120.0, damping_ratio: float = 1.0):
        self.x = self.target = float(value)
        self.v = 0.0
        self.k = float(stiffness)
        self.c = 2.0 * math.sqrt(self.k) * damping_ratio

    def step(self, dt: float) -> None:
        if dt <= 0.0:
            return
        n = max(1, int(math.ceil(dt / MAX_SUBSTEP)))
        h = dt / n
        for _ in range(n):
            a = self.k * (self.target - self.x) - self.c * self.v
            self.v += a * h
            self.x += self.v * h


@dataclass
class Frame:
    """Valores finais de um quadro: e o que o renderer desenha."""
    w: float = BASE["w"]
    h: float = BASE["h"]
    round: float = BASE["round"]
    gap: float = BASE["gap"]
    open: float = BASE["open"]
    lid_top: float = BASE["lid_top"]
    lid_slant: float = BASE["lid_slant"]
    lid_bottom: float = BASE["lid_bottom"]
    glow: float = BASE["glow"]
    x_mix: float = BASE["x_mix"]
    asym: float = BASE["asym"]
    dy: float = BASE["dy"]
    gx: float = 0.0     # olhar horizontal  -1 (esquerda) .. 1 (direita)
    gy: float = 0.0     # olhar vertical    -1 (cima)     .. 1 (baixo)


@dataclass
class IdleSettings:
    blink_min_s: float = 2.0
    blink_max_s: float = 6.0
    saccades: bool = True
    breathing: bool = True


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class EyeAnimator:
    def __init__(self, idle: Optional[IdleSettings] = None, mood: Mood = Mood.NEUTRAL,
                 rng: Optional[random.Random] = None):
        self.idle = idle or IdleSettings()
        self.rng = rng or random.Random()
        self.t = 0.0
        self.mood = mood
        self.preset = PRESETS[mood]
        self._springs = {n: Spring(self.preset.target(n), *SPRING_TUNING[n]) for n in PARAMS}
        self._gx = Spring(self.preset.gaze[0], 260.0, 0.7)
        self._gy = Spring(self.preset.gaze[1], 260.0, 0.7)
        self._speech = Spring(0.0, 500.0, 1.0)
        self._speech_external: Optional[float] = None
        self._manual_until = 0.0
        self._blink_p: Optional[float] = None
        self._blink_dur = 0.17
        self._double_pending = False
        self._next_blink = math.inf
        self._next_saccade = 1.2
        self._next_jitter = 0.0
        self._jx = self._jy = 0.0
        self._glow_flicker = 1.0
        self._schedule_blink()

    # ------------------------------------------------------------------ comandos
    def set_mood(self, mood: Mood) -> None:
        self.mood = mood
        self.preset = PRESETS[mood]
        for name, spring in self._springs.items():
            spring.target = self.preset.target(name)
        if self.t >= self._manual_until:
            self._gx.target, self._gy.target = self.preset.gaze
        self._next_saccade = self.t + 0.8
        self._schedule_blink()

    def look_at(self, x: float, y: float, hold: float = 1.5) -> None:
        """Olha para (x, y) em -1..1 por `hold` segundos e depois volta ao comportamento normal."""
        self._gx.target = _clamp(x, -1.0, 1.0)
        self._gy.target = _clamp(y, -1.0, 1.0)
        self._manual_until = self.t + max(0.0, hold)

    def set_speech_level(self, level: Optional[float]) -> None:
        """Volume da fala (0..1) vindo do audio real. None = animacao procedural."""
        self._speech_external = None if level is None else _clamp(level, 0.0, 1.0)

    def blink_now(self) -> None:
        if self._blink_p is None:
            self._blink_p = 0.0

    # ------------------------------------------------------------------ quadro a quadro
    def update(self, dt: float) -> Frame:
        dt = _clamp(dt, 0.0, 0.1)
        self.t += dt
        p = self.preset

        self._update_blink(dt)
        self._update_saccade()
        for spring in self._springs.values():
            spring.step(dt)
        self._gx.step(dt)
        self._gy.step(dt)
        speech = self._update_speech(dt)
        self._update_jitter()

        s = {n: sp.x for n, sp in self._springs.items()}
        breathe = 1.0
        if self.idle.breathing:
            breathe += 0.014 * p.breathe * math.sin(self.t * 2.0 * math.pi / 4.4)
        glow = s["glow"] * (1.0 + 0.25 * p.pulse * speech) * self._glow_flicker
        if p.flash:
            glow *= 1.0 + 0.35 * p.flash * math.sin(self.t * 2.0 * math.pi * 2.4)
        blink = self._blink_amount()

        return Frame(
            w=s["w"] * (1.0 + 0.02 * p.pulse * speech),
            h=s["h"] * breathe * (1.0 + 0.09 * p.pulse * speech),
            round=_clamp(s["round"], 0.0, 1.0),
            gap=s["gap"],
            open=max(0.0, s["open"] * (1.0 - 0.96 * blink)),
            lid_top=_clamp(s["lid_top"], 0.0, 0.95),
            lid_slant=_clamp(s["lid_slant"], -1.2, 1.2),
            lid_bottom=_clamp(s["lid_bottom"], 0.0, 0.95),
            glow=max(0.0, glow),
            x_mix=_clamp(s["x_mix"], 0.0, 1.0),
            asym=_clamp(s["asym"], -1.0, 1.0),
            dy=s["dy"],
            gx=_clamp(self._gx.x + self._jx, -1.2, 1.2),
            gy=_clamp(self._gy.x + self._jy, -1.2, 1.2),
        )

    # ------------------------------------------------------------------ comportamentos
    def _schedule_blink(self) -> None:
        rate = self.preset.blink
        if rate <= 0.0:
            self._next_blink = math.inf
            return
        self._next_blink = self.t + self.rng.uniform(self.idle.blink_min_s, self.idle.blink_max_s) / rate

    def _update_blink(self, dt: float) -> None:
        if self._blink_p is None:
            if self.t >= self._next_blink:
                self._blink_p = 0.0
                self._blink_dur = 0.17 * (1.8 if self.mood is Mood.SLEEPY else 1.0)
            return
        self._blink_p += dt / self._blink_dur
        if self._blink_p >= 1.0:
            self._blink_p = None
            if not self._double_pending and self.rng.random() < 0.18 and self.preset.blink > 0.0:
                self._double_pending = True          # piscada dupla
                self._next_blink = self.t + 0.12
            else:
                self._double_pending = False
                self._schedule_blink()

    def _blink_amount(self) -> float:
        p = self._blink_p
        if p is None:
            return 0.0
        if p < 0.38:                                  # fecha rapido
            x = p / 0.38
            return x * x * (3.0 - 2.0 * x)
        x = (p - 0.38) / 0.62                         # abre mais devagar
        return 1.0 - x * x * (3.0 - 2.0 * x)

    def _update_saccade(self) -> None:
        if self.t < self._manual_until:
            return
        bx, by = self.preset.gaze
        if self._manual_until:                         # acabou o olhar manual: volta ao normal
            self._manual_until = 0.0
            self._gx.target, self._gy.target = bx, by
        amp = self.preset.wander
        if not self.idle.saccades or amp <= 0.0:
            self._gx.target, self._gy.target = bx, by
            return
        if self.t >= self._next_saccade:
            if self.rng.random() < 0.3:
                tx, ty = bx, by                        # volta ao centro de descanso
            else:
                tx = bx + self.rng.uniform(-1.0, 1.0) * 0.55 * amp
                ty = by + self.rng.uniform(-1.0, 1.0) * 0.30 * amp
            self._gx.target, self._gy.target = _clamp(tx, -1.0, 1.0), _clamp(ty, -1.0, 1.0)
            self._next_saccade = self.t + self.rng.uniform(1.0, 3.6)

    def _update_speech(self, dt: float) -> float:
        if self.preset.pulse <= 0.0:
            target = 0.0
        elif self._speech_external is not None:
            target = self._speech_external
        else:                                          # fala simulada: silabas com pausas
            t = self.t
            target = 0.5 + 0.5 * math.sin(t * 17.0) * math.sin(t * 4.1 + 0.6)
            target *= 0.55 + 0.45 * math.sin(t * 1.3 + 2.0) ** 2
        self._speech.target = _clamp(target, 0.0, 1.0)
        self._speech.step(dt)
        return self._speech.x

    def _update_jitter(self) -> None:
        if self.preset.jitter <= 0.0:
            self._jx = self._jy = 0.0
            self._glow_flicker = 1.0
            return
        if self.t >= self._next_jitter:                # ~25 vezes por segundo
            j = self.preset.jitter
            self._jx = self.rng.uniform(-1.0, 1.0) * 0.06 * j
            self._jy = self.rng.uniform(-1.0, 1.0) * 0.04 * j
            self._glow_flicker = 0.75 + 0.5 * self.rng.random()
            self._next_jitter = self.t + 0.04
