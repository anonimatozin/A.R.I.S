"""ARIS Gesture Trainer — núcleo (sem câmera/tela)."""

import numpy as np
import pytest

from gesture_trainer import training as T
from gesture_trainer.api import gesture_payload
from gesture_trainer.config import DEFAULT_GESTURES
from gesture_trainer.dataset import Dataset
from gesture_trainer.features import displacement, normalize, wrist_track
from gesture_trainer.gestures import add_gesture, delete_gesture, rename_gesture
from gesture_trainer.models import load as load_model
from gesture_trainer.models import save as save_model
from gesture_trainer.recognition import Recognizer


def fake_hand(dx=0.0, spread=1.0, curl=0.0):
    pts = [(dx + (i % 5) * 0.02 * spread, (i // 5) * 0.05 * spread) for i in range(21)]
    pts[0] = (dx, 0.0)
    pts[9] = (dx + 0.05 * spread, 0.1 * spread)
    pts[8] = (dx + 0.06 * spread, (0.15 - curl) * spread)  # ponta do indicador varia
    return pts


def test_normalize_invariante_translacao_escala():
    a = normalize(fake_hand())
    b = normalize(fake_hand(dx=0.4, spread=2.0))
    assert np.allclose(a, b, atol=1e-6)


def test_normalize_rejeita_curto():
    with pytest.raises(ValueError):
        normalize([(0, 0)] * 5)


def test_wrist_track_resample_e_deslocamento():
    track = [(i * 0.01, 0.0, i * 0.03) for i in range(20)]
    traj = wrist_track(track)
    assert len(traj) == 16
    d, v = displacement(track)
    assert d > 0 and v > 0


def test_dataset_roundtrip_e_qualidade(tmp_path):
    ds = Dataset(tmp_path)
    for i in range(12):
        ds.add_static("right", "pinca", fake_hand(dx=i * 0.01, spread=1.0 + i * 0.05,
                                                  curl=i * 0.01))
    assert ds.count("right", "pinca") == 12
    assert len(ds.load("right", "pinca")) == 12
    q, _ = ds.quality("right", "pinca")
    assert q == "BOA"
    q2, _ = ds.quality("right", "vazio")
    assert q2 == "RUIM"


def test_train_predict_e_cooldown():
    xs_a = [normalize(fake_hand(dx=i * 0.01)) for i in range(8)]
    xs_b = [normalize(fake_hand(dx=0.5 + i * 0.01)) for i in range(8)]
    model = T.train_static({"a": xs_a, "b": xs_b})
    rec = Recognizer(model, min_conf=0.0, cooldown=10.0)
    g, conf = rec.predict_static(normalize(fake_hand()), now=100.0)
    assert g == "a" and conf > 0
    g2, _ = rec.predict_static(normalize(fake_hand()), now=101.0)
    assert g2 is None  # cooldown
    g3, _ = rec.predict_static(normalize(fake_hand()), now=200.0)
    assert g3 == "a"


def test_dynamic_train_predict():
    seqs = [[[ [i * 0.01, 0.0] for i in range(16)]] for _ in range(6)]
    seqs = [[ [p[0] + k * 0.001, p[1]] for p in s[0]] for k, s in enumerate(seqs)]
    model = T.train_dynamic({"swipe": seqs})
    rec = Recognizer(model, min_conf=0.0, cooldown=0.0)
    g, conf = rec.predict_dynamic(seqs[0])
    assert g == "swipe" and conf > 0


def test_gestures_crud(tmp_path):
    ds = Dataset(tmp_path)
    add_gesture(ds, "right", "novo")
    assert (tmp_path / "right" / "novo").is_dir()
    assert rename_gesture(ds, "right", "novo", "novo2") is True
    delete_gesture(ds, "right", "novo2")
    assert not (tmp_path / "right" / "novo2").exists()


def test_models_save_load(tmp_path):
    xs = [normalize(fake_hand(dx=i * 0.01)) for i in range(6)]
    static = T.train_static({"a": xs})
    p = tmp_path / "aris_gestures.model"
    save_model(p, static, {}, {"v": 1})
    s2, d2, meta = load_model(p)
    assert "a" in s2 and meta["v"] == 1 and d2 == {}


def test_api_payload_formato():
    p = gesture_payload("pinch", "right", 0.94)
    assert p["gesture"] == "pinch" and p["hand"] == "right"
    assert p["confidence"] == 0.94 and "timestamp" in p


def test_default_gestures_14():
    assert len(DEFAULT_GESTURES) == 14
