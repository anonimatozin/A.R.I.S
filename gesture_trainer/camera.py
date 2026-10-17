"""Captura da webcam com FPS/resolução (§1-§2, §19)."""

import time

import cv2


class Camera:
    def __init__(self, index=0, width=640, height=480):
        self.index = index
        self.width = width
        self.height = height
        self.cap = None
        self._t = time.time()
        self.fps = 0.0

    def open(self):
        self.cap = cv2.VideoCapture(self.index)
        if not self.cap.isOpened():
            self.cap = None
            return False
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        return True

    @property
    def resolution(self):
        if not self.cap:
            return (0, 0)
        return (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    def read(self):
        if not self.cap:
            return False, None
        ok, frame = self.cap.read()
        now = time.time()
        dt = now - self._t
        if dt > 0:
            self.fps += (1.0 / dt - self.fps) * 0.1
        self._t = now
        return ok, frame

    def brightness(self, frame):
        import cv2 as _cv
        gray = _cv.cvtColor(frame, _cv.COLOR_BGR2GRAY)
        return float(gray.mean())

    def close(self):
        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass
        self.cap = None
