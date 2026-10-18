"""Props: enfeites animados em volta/sobre os olhos (fone, notas musicais, coracoes, zzz...).

Matematica pura (sem Qt), no mesmo espirito do animator.py: testavel sem tela. O motor devolve, a cada
quadro, uma lista de ``Item`` (o que desenhar e onde); quem pinta e o ``props_renderer.py``.

Coordenadas: o mesmo "espaco de desenho" de 1000 x 560 do renderer (olhos centrados em 500, 280).

Props disponiveis (nome -> o que e):
    notes       notas musicais subindo pelos lados            eye_heart   olhos viram coracoes
    equalizer   barrinhas de equalizador embaixo              eye_spiral  espiral girando (tonto)
    headphones  fone de ouvido que balanca no ritmo           eye_star    olhos viram estrelas
    hearts      coracoezinhos flutuando                       wink        olho direito vira "^"
    zzz         "Z z z" subindo (sono)                        blush       bochechas rosadas
    sparkles    brilhinhos piscando em volta                  tears       lagrimas escorrendo
    confetti    explosao de confete (uma vez)                 sweat       gota de suor (nervoso)
    loading     tres bolinhas pulando                         question    "?" balancando
    battery     bateria fraca piscando                        exclaim     "!" pulsando
    signal      ondas de conexao (wifi/bluetooth/ESP32)

Dois grupos de props ficam ativos ao mesmo tempo:
  - props do HUMOR (``sync_mood``): trocam sozinhos quando o humor muda (ver MOOD_PROPS em presets.py);
  - props MANUAIS (``add``/``remove``): ligados pela ARIS ou por uma cena, com tempo de vida opcional.

Cada prop aparece e some com fade (``appear`` 0..1), nunca "de repente".
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable, Optional

PROP_NAMES = (
    "notes", "equalizer", "headphones", "hearts", "zzz", "sparkles", "confetti", "tears", "sweat",
    "question", "exclaim", "loading", "blush", "battery", "signal",
    "eye_heart", "eye_spiral", "eye_star", "wink",
)

# props que, ligados sem tempo, se desligam sozinhos depois de N segundos
DEFAULT_TTL: dict[str, float] = {"wink": 1.2, "confetti": 3.2, "signal": 2.6}

FADE_RATE = 5.0            # velocidade do fade in/out (1/s): ~0,2 s para aparecer ou sumir
MAX_PARTICLES = 160        # teto de segurança (CPU) para particulas vivas
BAR_COUNT = 9              # barras do equalizador

CONFETTI_COLORS = ("#ff5c8a", "#ffd24a", "#4ade80", "#38bdf8", "#c084fc", "#fb923c")


@dataclass
class Item:
    """Uma coisa a desenhar neste quadro."""
    kind: str                       # nome do desenho (note, heart, headphones, eye_heart...)
    x: float = 500.0
    y: float = 280.0
    size: float = 1.0
    rot: float = 0.0                # radianos
    alpha: float = 1.0
    phase: float = 0.0              # tempo/fase para animacoes proprias do desenho
    variant: int = 0
    color: Optional[str] = None     # None = cor do tema/accent
    data: tuple = ()                # extras (alturas do equalizador, batida...)
    side: int = 0                   # olhos: 0 ambos, -1 esquerdo, +1 direito


@dataclass
class PropFrame:
    items: list = field(default_factory=list)
    beat: float = 0.0               # 0..1, pulso do ritmo (use para fazer os olhos pulsarem)
    time: float = 0.0


class _Particle:
    __slots__ = ("kind", "x", "y", "vx", "vy", "ay", "age", "life", "size", "size_end", "rot", "vrot",
                 "variant", "color", "sway", "swayf", "phase", "owner")

    def __init__(self, kind: str, owner: str, x: float, y: float, vx: float, vy: float, life: float,
                 size: float, *, ay: float = 0.0, size_end: Optional[float] = None, rot: float = 0.0,
                 vrot: float = 0.0, variant: int = 0, color: Optional[str] = None, sway: float = 0.0,
                 swayf: float = 2.0, phase: float = 0.0):
        self.kind, self.owner = kind, owner
        self.x, self.y, self.vx, self.vy, self.ay = x, y, vx, vy, ay
        self.age, self.life = 0.0, life
        self.size = size
        self.size_end = size if size_end is None else size_end
        self.rot, self.vrot = rot, vrot
        self.variant, self.color = variant, color
        self.sway, self.swayf, self.phase = sway, swayf, phase


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class PropEngine:
    def __init__(self, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()
        self.t = 0.0
        self.bpm = 118.0                         # ritmo da batida simulada
        self._mood_props: set = set()
        self._manual: dict = {}                  # nome -> instante em que expira (None = nunca)
        self._appear: dict = {}                  # nome -> 0..1
        self._parts: list = []
        self._next_spawn: dict = {}
        self._level: Optional[float] = None      # volume da musica real (0..1); None = batida simulada
        self._bars = [0.0] * BAR_COUNT
        self._beat = 0.0
        self._burst: list = []                   # confete pendente

    # ------------------------------------------------------------------ comandos
    def sync_mood(self, names: Iterable[str]) -> None:
        """Define os props do humor atual (substitui os do humor anterior; os manuais ficam)."""
        self._mood_props = {n for n in names if n in PROP_NAMES}

    def add(self, name: str, seconds: Optional[float] = None) -> bool:
        """Liga um prop manualmente. ``seconds`` = tempo de vida (None = o padrao do prop, se houver)."""
        name = (name or "").strip().lower()
        if name not in PROP_NAMES:
            return False
        ttl = seconds if seconds is not None else DEFAULT_TTL.get(name)
        self._manual[name] = None if not ttl or ttl <= 0 else self.t + float(ttl)
        if name == "confetti":
            self._burst.append(name)
        return True

    def remove(self, name: str) -> bool:
        name = (name or "").strip().lower()
        had = name in self._manual or name in self._mood_props
        self._manual.pop(name, None)
        self._mood_props.discard(name)
        return had

    def clear(self, include_mood: bool = True) -> None:
        self._manual.clear()
        if include_mood:
            self._mood_props.clear()

    def set_level(self, level: Optional[float]) -> None:
        """Volume (0..1) da musica real. None volta para a batida simulada (``bpm``)."""
        self._level = None if level is None else _clamp(float(level), 0.0, 1.0)

    # ------------------------------------------------------------------ consulta
    def active_names(self) -> set:
        return set(self._mood_props) | set(self._manual)

    @property
    def beat(self) -> float:
        return self._beat

    @property
    def is_animating(self) -> bool:
        """True se ha algo para repintar (props ativos ou sumindo, particulas vivas)."""
        return bool(self._appear or self._parts or self._manual or self._mood_props)

    # ------------------------------------------------------------------ quadro a quadro
    def update(self, dt: float) -> PropFrame:
        dt = _clamp(dt, 0.0, 0.1)
        self.t += dt
        self._expire()
        self._update_appear(dt)
        self._update_beat()
        items: list = []
        self._persistent_items(items, dt)
        self._spawn(dt)
        self._step_particles(dt, items)
        return PropFrame(items=items, beat=self._beat, time=self.t)

    # ------------------------------------------------------------------ internos
    def _expire(self) -> None:
        for name in [n for n, exp in self._manual.items() if exp is not None and self.t >= exp]:
            del self._manual[name]

    def _update_appear(self, dt: float) -> None:
        active = self.active_names()
        for name in active:
            self._appear.setdefault(name, 0.0)
        step = FADE_RATE * dt
        for name in list(self._appear):
            target = 1.0 if name in active else 0.0
            cur = self._appear[name]
            cur = min(target, cur + step) if cur < target else max(target, cur - step)
            if cur <= 0.001 and target == 0.0:
                del self._appear[name]
                self._next_spawn.pop(name, None)
            else:
                self._appear[name] = cur

    def _update_beat(self) -> None:
        phase = self.t * self.bpm / 60.0 * 2.0 * math.pi
        base = ((1.0 + math.cos(phase)) / 2.0) ** 3
        self._beat = base if self._level is None else base * (0.35 + 0.65 * self._level)

    def _ap(self, name: str) -> float:
        return self._appear.get(name, 0.0)

    def _persistent_items(self, items: list, dt: float) -> None:
        t, beat = self.t, self._beat
        for name in ("blush", "eye_heart", "eye_star", "eye_spiral", "wink"):
            a = self._ap(name)
            if a <= 0.0:
                continue
            if name == "blush":
                items.append(Item("blush", alpha=a * 0.85))
            elif name == "eye_heart":
                size = 1.0 + 0.07 * math.sin(t * 7.0) + 0.06 * beat
                items.append(Item("eye_heart", size=size, alpha=a, phase=t))
            elif name == "eye_star":
                items.append(Item("eye_star", size=1.0 + 0.06 * math.sin(t * 5.0), rot=0.2 * math.sin(t * 2.4),
                                  alpha=a, phase=t))
            elif name == "eye_spiral":
                items.append(Item("eye_spiral", rot=t * 5.5, alpha=a, phase=t))
            else:
                items.append(Item("wink", alpha=a, side=1, phase=t))
        if self._ap("headphones") > 0.0:
            items.append(Item("headphones", alpha=self._ap("headphones"), phase=t, data=(beat,)))
        if self._ap("equalizer") > 0.0:
            items.append(Item("equalizer", alpha=self._ap("equalizer"), data=tuple(self._step_bars(dt))))
        if self._ap("loading") > 0.0:
            items.append(Item("loading", alpha=self._ap("loading"), phase=t))
        if self._ap("question") > 0.0:
            items.append(Item("question", x=895.0, y=120.0 + 8.0 * math.sin(t * 3.0),
                              rot=0.12 * math.sin(t * 2.2), alpha=self._ap("question"), phase=t))
        if self._ap("exclaim") > 0.0:
            pop = 1.0 + 0.12 * max(0.0, math.sin(t * 9.0))
            items.append(Item("exclaim", x=890.0, y=120.0, size=pop, alpha=self._ap("exclaim"), phase=t))
        if self._ap("sweat") > 0.0:
            k = (t * 0.55) % 1.0
            items.append(Item("sweat", x=838.0, y=150.0 + 120.0 * k,
                              alpha=self._ap("sweat") * (1.0 - max(0.0, (k - 0.7) / 0.3)), phase=t))
        if self._ap("battery") > 0.0:
            items.append(Item("battery", x=500.0, y=508.0, alpha=self._ap("battery"), phase=t))
        if self._ap("signal") > 0.0:
            items.append(Item("signal", x=500.0, y=96.0, alpha=self._ap("signal"), phase=t))

    def _step_bars(self, dt: float) -> list:
        level = 0.55 + 0.45 * self._beat if self._level is None else self._level
        k = min(1.0, dt * 14.0)
        for i in range(BAR_COUNT):
            wobble = 0.5 + 0.5 * math.sin(self.t * (3.1 + 0.9 * i) + i * 1.7)
            target = _clamp(level * (0.35 + 0.65 * wobble) * (0.8 + 0.4 * self._beat), 0.1, 1.0)
            self._bars[i] += (target - self._bars[i]) * k
        return self._bars

    # -- particulas ----------------------------------------------------------
    def _wants(self, name: str) -> bool:
        return name in self.active_names() and self._ap(name) > 0.25

    def _spawn(self, dt: float) -> None:
        r = self.rng
        t = self.t
        if self._burst:
            self._burst.clear()
            self._spawn_confetti()
        for name, interval, fn in (
            ("notes", 0.5, self._spawn_note),
            ("hearts", 0.55, self._spawn_heart),
            ("zzz", 1.5, self._spawn_zzz),
            ("sparkles", 0.18, self._spawn_sparkle),
            ("tears", 0.4, self._spawn_tear),
        ):
            if not self._wants(name):
                continue
            due = self._next_spawn.get(name, 0.0)
            if t >= due and len(self._parts) < MAX_PARTICLES:
                fn()
                self._next_spawn[name] = t + interval * r.uniform(0.7, 1.4)

    def _spawn_note(self) -> None:
        r = self.rng
        left = r.random() < 0.5
        if self._wants("headphones"):            # com fone, as notas saem das conchas
            x, y0 = (92.0 if left else 908.0) + r.uniform(-14.0, 14.0), r.uniform(175.0, 205.0)
        else:
            x = r.uniform(85.0, 190.0) if left else r.uniform(810.0, 915.0)
            y0 = r.uniform(330.0, 440.0)
        self._parts.append(_Particle("note", "notes", x, y0, 0.0, -r.uniform(55.0, 90.0),
                                     r.uniform(3.0, 3.8), r.uniform(26.0, 38.0), variant=r.randint(0, 1),
                                     rot=r.uniform(-0.25, 0.25), sway=r.uniform(14.0, 26.0),
                                     swayf=r.uniform(1.6, 2.6), phase=r.uniform(0.0, 6.28)))

    def _spawn_heart(self) -> None:
        r = self.rng
        left = r.random() < 0.5
        x = r.uniform(70.0, 190.0) if left else r.uniform(810.0, 930.0)
        self._parts.append(_Particle("heart", "hearts", x, r.uniform(300.0, 430.0), 0.0,
                                     -r.uniform(55.0, 85.0), r.uniform(2.6, 3.4), r.uniform(26.0, 42.0),
                                     rot=r.uniform(-0.3, 0.3), sway=r.uniform(10.0, 22.0),
                                     swayf=r.uniform(1.8, 3.0), phase=r.uniform(0.0, 6.28)))

    def _spawn_zzz(self) -> None:
        self._parts.append(_Particle("zzz", "zzz", 760.0, 140.0, 28.0, -34.0, 3.2, 24.0, size_end=58.0,
                                     rot=-0.1, sway=6.0, swayf=1.5))

    def _spawn_sparkle(self) -> None:
        r = self.rng
        ang = r.uniform(0.0, 6.2832)
        x = 500.0 + math.cos(ang) * r.uniform(330.0, 440.0)
        y = 280.0 + math.sin(ang) * r.uniform(210.0, 265.0)
        self._parts.append(_Particle("sparkle", "sparkles", x, y, 0.0, 0.0, r.uniform(0.8, 1.4),
                                     r.uniform(16.0, 32.0), vrot=r.uniform(-1.5, 1.5)))

    def _spawn_tear(self) -> None:
        r = self.rng
        for cx in (300.0, 700.0):
            self._parts.append(_Particle("tear", "tears", cx + r.uniform(-50.0, 50.0), 440.0, 0.0,
                                         r.uniform(20.0, 45.0), r.uniform(1.7, 2.2), r.uniform(17.0, 24.0),
                                         ay=170.0))

    def _spawn_confetti(self) -> None:
        r = self.rng
        for _ in range(70):
            if len(self._parts) >= MAX_PARTICLES + 70:
                break
            self._parts.append(_Particle("confetti", "confetti", 500.0 + r.uniform(-60.0, 60.0), 40.0,
                                         r.uniform(-430.0, 430.0), r.uniform(-120.0, 260.0), r.uniform(2.2, 3.0),
                                         r.uniform(8.0, 14.0), ay=420.0, rot=r.uniform(0.0, 6.28),
                                         vrot=r.uniform(-9.0, 9.0), color=r.choice(CONFETTI_COLORS),
                                         variant=r.randint(0, 1)))

    def _step_particles(self, dt: float, items: list) -> None:
        alive = []
        for p in self._parts:
            p.age += dt
            if p.age >= p.life:
                continue
            p.vy += p.ay * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.rot += p.vrot * dt
            u = p.age / p.life
            fade = min(1.0, p.age / 0.25) * min(1.0, (p.life - p.age) / 0.6)
            fade *= min(1.0, self._ap(p.owner) * 1.6) if p.owner in self._appear else 0.0
            size = p.size + (p.size_end - p.size) * u
            if p.kind == "sparkle":
                size *= math.sin(u * math.pi)
            x = p.x + (p.sway * math.sin(p.age * p.swayf + p.phase) if p.sway else 0.0)
            if fade > 0.0:
                items.append(Item(p.kind, x=x, y=p.y, size=size, rot=p.rot, alpha=fade, variant=p.variant,
                                  color=p.color, phase=p.age))
            alive.append(p)
        self._parts = alive
