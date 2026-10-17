"""Features geométricas normalizadas a partir de landmarks 21x2.

Normalização (§11): origem no pulso, escala pelo comprimento
pulso→MCP do dedo médio, espelho opcional p/ mão esquerda. O modelo nunca
vê posição absoluta, tamanho ou distância — só relações relativas.
"""

import math

TIPS = (4, 8, 12, 16, 20)
MCPS = (2, 5, 9, 13, 17)


def normalize(lms):
    """21 landmarks [(x,y)] -> vetor de features invariante.

    42 coords normalizadas + 5 distâncias ponta-pulso + 2 orientação.
    """
    if len(lms) < 21:
        raise ValueError("esperados 21 landmarks")
    wx, wy = lms[0]
    scale = math.hypot(lms[9][0] - wx, lms[9][1] - wy) or 1e-6
    rel = [((x - wx) / scale, (y - wy) / scale) for x, y in lms]
    feats = [c for pt in rel for c in pt]
    feats += [math.hypot(rel[t][0], rel[t][1]) for t in TIPS]
    # orientação da palma (MCP indicador -> MCP mindinho, normalizada)
    dx, dy = rel[17][0] - rel[5][0], rel[17][1] - rel[5][1]
    n = math.hypot(dx, dy) or 1e-6
    feats += [dx / n, dy / n]
    return feats


def wrist_track(track):
    """Track [(x,y,t)] do pulso -> trajetória reamostrada (SEQ_LEN x 2).

    Usado em gestos dinâmicos: trajetória, direção e velocidade.
    """
    from .config import SEQ_LEN
    if not track:
        return [[0.0, 0.0]] * SEQ_LEN
    pts = [(p[0], p[1]) for p in track]
    if len(pts) == 1:
        return [list(pts[0])] * SEQ_LEN
    # comprimento acumulado
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.hypot(pts[i][0] - pts[i - 1][0],
                                        pts[i][1] - pts[i - 1][1]))
    total = cum[-1] or 1e-6
    # origem no início, escala pelo deslocamento total
    ox, oy = pts[0]
    out = []
    j = 0
    for k in range(SEQ_LEN):
        target = total * k / (SEQ_LEN - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = (cum[j + 1] - cum[j]) or 1e-6
        f = max(0.0, min(1.0, (target - cum[j]) / seg))
        x = pts[j][0] + (pts[j + 1][0] - pts[j][0]) * f
        y = pts[j][1] + (pts[j + 1][1] - pts[j][1]) * f
        out.append([(x - ox) / total, (y - oy) / total])
    return out


def displacement(track):
    """Deslocamento total + velocidade média (robustez p/ dinâmicos)."""
    if len(track) < 2:
        return 0.0, 0.0
    d = math.hypot(track[-1][0] - track[0][0], track[-1][1] - track[0][1])
    dt = max(1e-6, track[-1][2] - track[0][2])
    return d, d / dt
