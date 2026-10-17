"""ARIS Gesture Trainer — ponto de entrada.

Uso:
    python -m gesture_trainer.main            # wizard completo
    python -m gesture_trainer.main --validate # só validação (modelo existe)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gesture_trainer.camera import Camera
from gesture_trainer.config import DATA_DIR
from gesture_trainer.dataset import Dataset
from gesture_trainer.hand_tracking import Tracker
from gesture_trainer.ui import Wizard


def main():
    ap = argparse.ArgumentParser(description="ARIS Gesture Trainer")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()

    from pathlib import Path as P
    ds = Dataset(P(args.data_dir))
    cam = Camera(index=args.camera)
    if not cam.open():
        print("ERRO: webcam indisponível (índice %d)" % args.camera)
        return 1
    print(f"Câmera OK: {cam.resolution[0]}x{cam.resolution[1]}")

    model_path = P(args.data_dir).parent / "hand_landmarker.task"
    if not model_path.exists():
        # reutiliza o modelo do HUD se existir
        alt = P(__file__).resolve().parent.parent / "data" / "hand_landmarker.task"
        if alt.exists():
            model_path = alt
    tracker = Tracker(model_path)
    try:
        tracker.start()
    except Exception as e:
        print(f"ERRO: hand tracking indisponível: {e}")
        return 1

    try:
        Wizard(cam, tracker, ds).run()
    finally:
        cam.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
