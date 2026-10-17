"""Verificações de posição da etapa AJUSTE (§3).

Retorna checklist: visível, posição, distância, confiança, luz, estável.
"""

import math


class PositionCheck:
    def __init__(self):
        self._prev = None
        self._stable_n = 0

    def check(self, landmarks, confidence, brightness, w=1.0, h=1.0):
        n = len(landmarks) if landmarks else 0
        visible = n >= 18
        xs = [p[0] for p in landmarks] if landmarks else []
        ys = [p[1] for p in landmarks] if landmarks else []
        inside = bool(xs) and min(xs) > 0.05 and max(xs) < 0.95 and min(ys) > 0.05 and max(ys) < 0.95
        spread = (max(xs) - min(xs)) if xs else 0.0
        too_close = spread > 0.75
        too_far = 0 < spread < 0.18
        dist_ok = visible and not too_close and not too_far
        conf_ok = confidence >= 0.5
        light_ok = brightness >= 40
        # estabilidade: centro do pulso parado
        stable = False
        if landmarks:
            c = landmarks[0]
            if self._prev and math.hypot(c[0] - self._prev[0], c[1] - self._prev[1]) < 0.02:
                self._stable_n += 1
            else:
                self._stable_n = 0
            self._prev = c
            stable = self._stable_n >= 10
        checks = {
            "Mão detectada": visible,
            "Posição adequada": visible and inside,
            "Distância adequada": dist_ok,
            "Confiança adequada": conf_ok,
            "Luz suficiente": light_ok,
            "Estável": stable,
        }
        if too_close:
            checks["Distância adequada"] = False
        return checks

    @staticmethod
    def ready(checks):
        return all(checks.values())
