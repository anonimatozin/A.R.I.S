"""Persistência do modelo: aris_gestures.model (JSON + centroides)."""

import json
import time

import numpy as np


def save(path, static_model, dynamic_model, meta):
    out = {"saved_at": time.time(), "meta": meta, "static": {}, "dynamic": {}}
    for g, m in static_model.items():
        out["static"][g] = {"centroid": np.asarray(m["centroid"]).tolist(),
                            "threshold": m["threshold"], "n": m["n"]}
    for g, m in dynamic_model.items():
        out["dynamic"][g] = {"centroid": np.asarray(m["centroid"]).tolist(),
                             "threshold": m["threshold"], "n": m["n"]}
    path.write_text(json.dumps(out), encoding="utf-8")


def load(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    static = {g: {"centroid": np.asarray(m["centroid"]),
                  "threshold": m["threshold"], "n": m["n"], "dynamic": False}
              for g, m in raw.get("static", {}).items()}
    dynamic = {g: {"centroid": np.asarray(m["centroid"]),
                   "threshold": m["threshold"], "n": m["n"], "dynamic": True}
               for g, m in raw.get("dynamic", {}).items()}
    return static, dynamic, raw.get("meta", {})
