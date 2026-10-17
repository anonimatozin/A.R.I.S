"""Reconhecimento em tempo real: predição + cooldown + confiança mínima.

Evita falsos positivos e Rajadas (§19): mesmo gesto só dispara de novo
após COOLDOWN_S; abaixo de MIN_CONFIDENCE, silêncio.
"""

import time

from . import training as T


class Recognizer:
    def __init__(self, model, min_conf=0.60, cooldown=1.0):
        self.model = model
        self.min_conf = min_conf
        self.cooldown = cooldown
        self._last_fire = {}
        self.last = (None, 0.0)

    def update_threshold(self, min_conf):
        self.min_conf = min_conf

    def _cooled(self, gesture, now):
        return now - self._last_fire.get(gesture, 0.0) >= self.cooldown

    def predict_static(self, vec, now=None):
        now = time.time() if now is None else now
        g, conf = T.predict_static(vec, self.model)
        self.last = (g, conf)
        if g is None or conf < self.min_conf or not self._cooled(g, now):
            return None, conf
        self._last_fire[g] = now
        return g, conf

    def predict_dynamic(self, traj, now=None):
        now = time.time() if now is None else now
        flat = [c for pt in traj for c in pt]
        best, best_d, best_t, dyn = None, float("inf"), 1.0, False
        for g, m in self.model.items():
            if not m.get("dynamic"):
                continue
            d = T.dist_to(flat, m["centroid"])
            if d < best_d:
                best, best_d, best_t, dyn = g, d, m["threshold"], True
        if best is None:
            return None, 0.0
        conf = max(0.0, 1.0 - best_d / (best_t * 1.5))
        self.last = (best, conf)
        if conf < self.min_conf or not self._cooled(best, now):
            return None, conf
        self._last_fire[best] = now
        return best, conf
