"""Hand tracking robusto via MediaPipe HandLandmarker (§2).

Retorna por mão: landmarks 21x2, handedness (Left/Right), confiança.
Mapeia Left/Right do MediaPipe (espelho) para esquerda/direita reais.
"""

import cv2
import numpy as np


class Tracker:
    def __init__(self, model_path, num_hands=2):
        self.model_path = str(model_path)
        self.num_hands = num_hands
        self.landmarker = None
        self._idx = 0

    def start(self):
        import mediapipe as mp
        base = mp.tasks.BaseOptions(model_asset_path=self.model_path)
        opts = mp.tasks.vision.HandLandmarkerOptions(
            base_options=base,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=self.num_hands,
            min_hand_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.landmarker = mp.tasks.vision.HandLandmarker.create_from_options(opts)
        self._mp = mp

    def process(self, rgb_frame):
        """[(landmarks21, side, confidence)] — side: 'left'|'right'|'unknown'."""
        import mediapipe as mp
        if self.landmarker is None:
            return []
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb_frame))
        self._idx += 1
        try:
            res = self.landmarker.detect_for_video(img, self._idx * 33)
        except Exception:
            return []
        out = []
        lms = res.hand_landmarks or []
        handed = res.handedness or []
        for i, hand in enumerate(lms):
            pts = [(p.x, p.y) for p in hand]
            side, conf = "unknown", 0.0
            try:
                h = handed[i][0]
                # MediaPipe diz Left p/ mão que aparece à esquerda (espelho);
                # usuário de frente p/ câmera: inverter p/ lado real.
                side = {"Left": "right", "Right": "left"}.get(h.category_name, "unknown")
                conf = float(h.score or 0.0)
            except Exception:
                pass
            out.append((pts, side, conf))
        return out

    @staticmethod
    def draw(frame, landmarks):
        for i, (x, y) in enumerate(landmarks):
            px, py = int(x * frame.shape[1]), int(y * frame.shape[0])
            cv2.circle(frame, (px, py), 3 if i else 5, (0, 255, 255), -1)
        for a, b in [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7),
                     (7, 8), (5, 9), (9, 10), (10, 11), (11, 12), (9, 13),
                     (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
                     (18, 19), (19, 20), (0, 17)]:
            p1 = (int(landmarks[a][0] * frame.shape[1]), int(landmarks[a][1] * frame.shape[0]))
            p2 = (int(landmarks[b][0] * frame.shape[1]), int(landmarks[b][1] * frame.shape[0]))
            cv2.line(frame, p1, p2, (0, 200, 255), 1)
