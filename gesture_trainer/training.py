"""Treinamento local: k-NN por centroides (estáticos) + templates (dinâmicos).

Leve, sem dependências pagas, trocável (arquitetura modular §12):
landmarks -> features -> classificador -> gesto.
"""

import math

import numpy as np


def _centroid(X):
    return np.asarray(X, dtype=np.float64).mean(axis=0)


def _intra_threshold(X, centroid, k=2.0):
    d = np.linalg.norm(np.asarray(X, dtype=np.float64) - centroid, axis=1)
    return float(d.mean() + k * d.std() + 1e-6)


def train_static(samples_by_gesture):
    """{gesto: [vetores]} -> {gesto: {centroid, threshold, n}}."""
    model = {}
    for g, xs in samples_by_gesture.items():
        if len(xs) < 5:
            continue
        c = _centroid(xs)
        model[g] = {"centroid": c, "threshold": _intra_threshold(xs, c),
                    "n": len(xs), "dynamic": False}
    return model


def train_dynamic(seqs_by_gesture):
    """{gesto: [trajetórias SEQ_LENx2]} -> templates médios."""
    model = {}
    for g, seqs in seqs_by_gesture.items():
        if len(seqs) < 5:
            continue
        arr = np.asarray(seqs, dtype=np.float64)
        c = arr.mean(axis=0)
        flat = arr.reshape(len(arr), -1)
        model[g] = {"centroid": c, "threshold": _intra_threshold(flat, c.reshape(-1)),
                    "n": len(arr), "dynamic": True}
    return model


def dist_to(a, b):
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    n = min(len(a), len(b))
    return float(np.linalg.norm(a[:n] - b[:n]))


def predict_static(vec, model):
    """-> (gesto, confiança). Confiança cai com distância/threshold."""
    best, best_d, best_t = None, math.inf, 1.0
    for g, m in model.items():
        if m.get("dynamic"):
            continue
        d = dist_to(vec, m["centroid"])
        if d < best_d:
            best, best_d, best_t = g, d, m["threshold"]
    if best is None:
        return None, 0.0
    conf = max(0.0, 1.0 - best_d / (best_t * 1.5))
    return best, conf
