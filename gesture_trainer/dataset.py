"""Banco de dados de treinamento: gesture_data/{mão}/{gesto}/*.npz.

Cada exemplo guarda features + metadados (timestamp, variação pedida).
Qualidade (§8): variância mínima (anti-duplicata) e contagem.
"""

import json
import time

import numpy as np

from . import features as F

HANDS = ("right", "left", "both")


class Dataset:
    def __init__(self, root):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, hand, gesture):
        d = self.root / hand / gesture
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add_static(self, hand, gesture, landmarks, variation=""):
        vec = np.asarray(F.normalize(landmarks), dtype=np.float32)
        d = self._dir(hand, gesture)
        idx = len(list(d.glob("*.npz")))
        np.savez_compressed(d / f"{idx:04d}.npz", x=vec,
                            variation=np.asarray(variation),
                            ts=np.asarray(time.time()))
        return idx

    def add_dynamic(self, hand, gesture, track, variation=""):
        traj = np.asarray(F.wrist_track(track), dtype=np.float32)
        disp, speed = F.displacement(track)
        d = self._dir(hand, gesture)
        idx = len(list(d.glob("*.npz")))
        np.savez_compressed(d / f"{idx:04d}.npz", x=traj,
                            variation=np.asarray(variation),
                            ts=np.asarray(time.time()),
                            disp=np.asarray([disp, speed]))
        return idx

    def load(self, hand, gesture):
        d = self._dir(hand, gesture)
        out = []
        for f in sorted(d.glob("*.npz")):
            try:
                z = np.load(f, allow_pickle=True)
                out.append(np.asarray(z["x"], dtype=np.float32))
            except Exception:
                continue
        return out

    def count(self, hand, gesture):
        return len(list(self._dir(hand, gesture).glob("*.npz")))

    def quality(self, hand, gesture):
        """BOA/RUIM + motivo (§8)."""
        xs = self.load(hand, gesture)
        n = len(xs)
        if n < 10:
            return "RUIM", f"poucos exemplos ({n})"
        X = np.stack([x.ravel() for x in xs])
        var = float(X.var())
        if var < 1e-8:
            return "RUIM", "exemplos idênticos (sem variação)"
        # duplicatas aproximadas
        d = np.linalg.norm(X[:, None, :] - X[None, :, :], axis=-1)
        np.fill_diagonal(d, np.inf)
        if float((d < 1e-6).sum()) > n:
            return "RUIM", "muitas duplicatas — varie o gesto"
        return "BOA", f"{n} exemplos, var={var:.4f}"

    def clear(self, hand, gesture):
        for f in self._dir(hand, gesture).glob("*.npz"):
            try:
                f.unlink()
            except OSError:
                pass

    # — metadados —
    def save_meta(self, meta: dict):
        (self.root / "meta.json").write_text(json.dumps(meta, indent=2),
                                             encoding="utf-8")

    def load_meta(self) -> dict:
        try:
            return json.loads((self.root / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            return {}
