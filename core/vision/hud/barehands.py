"""Motor de pinça adaptado de github.com/jaredrhod/barehands.

Jared Rhodenizer, AGPL-3.0-or-later. Espelho Python puro da lógica que roda
no index.html (contrast law, hysteresis, probation, speed-aware release,
peak-velocity) para permitir testes automatizados dos gestos sobre
elementos reais (cards, holograma). Sem camada cognitiva nova.
"""

from __future__ import annotations

import math


def contrast_ok(back_mean: float, f8v: float, aspect: float, t_rel: float) -> bool:
    """OK-sign contrast law (barehands v3.8.2/v3.8.5)."""
    return (back_mean - f8v > 0.18 and back_mean > 1.30) or (aspect < 2.0 and t_rel > 0.95)


def pinch_enter(ratio: float, aspect: float, ok_now: bool, ok_ema: float) -> bool:
    """Barra de entrada com hysteresis por regime de orientação."""
    ceiling = 0.38 if aspect < 2.0 else 0.32
    return ratio < ceiling and (ok_now or ok_ema > 0.55)


def release_bar(hand_speed_px_s: float) -> float:
    """Speed-aware release (barehands v3.9.8/v3.9.25)."""
    return 0.70 if hand_speed_px_s > 800 else 0.55


def peak_velocity(history: list[dict]) -> tuple[float, float]:
    """Peak velocity nos últimos ~200ms (barehands v3.6)."""
    best = (0.0, 0.0)
    best_mag = 0.0
    for i in range(1, len(history)):
        dt = (history[i]["t"] - history[i - 1]["t"]) / 1000.0
        if dt <= 0:
            continue
        vx = (history[i]["x"] - history[i - 1]["x"]) / dt
        vy = (history[i]["y"] - history[i - 1]["y"]) / dt
        mag = math.hypot(vx, vy)
        if mag > best_mag:
            best_mag = mag
            best = (vx, vy)
    return best


def probation_kill(bad_run: int) -> bool:
    """Probation 400ms/4 frames (barehands v3.9.15)."""
    return bad_run >= 4
