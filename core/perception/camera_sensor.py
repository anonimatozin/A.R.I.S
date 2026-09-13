"""Sensor de câmera do A.R.I.S.

Lê a câmera padrão (índice configurável) via OpenCV, quando disponível.
Sem OpenCV ou sem câmera em runtime, o sensor fica ``offline`` e
emite ZERO eventos — nada é simulado.

Percepções geradas:
    - movimento (diferença de frames em downscale);
    - presença de pessoas (detector HOG embutido do OpenCV, sem modelos).

Também armazena os últimos ``frame_history`` frames (downscaled) para
uso futuro (profundidade/objetos) sem estourar memória.
"""

from __future__ import annotations

from collections import deque
from typing import Any

try:
    import cv2  # type: ignore[import-untyped]

    HAS_CV2 = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    HAS_CV2 = False

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]
    HAS_NUMPY = False

from core.neural.events import EVENT_CAMERA, PRIORITY_HIGH, PRIORITY_NORMAL, Event
from core.perception.sensor import Sensor
from utils.logger import Logger

_FRAME_W, _FRAME_H = 160, 120


class CameraSensor(Sensor):
    """Sensor de câmera (movimento + detecção de pessoas)."""

    name = "camera"

    def __init__(
        self,
        event_bus=None,
        enabled: bool = False,
        interval: float = 2.0,
        logger: Logger | None = None,
        capture_index: int = 0,
        motion_threshold: float = 0.04,
        object_interval: float = 30.0,
        frame_history: int = 5,
    ) -> None:
        super().__init__(event_bus=event_bus, enabled=enabled, interval=interval, logger=logger)
        self._capture_index = int(capture_index)
        self._motion_threshold = float(motion_threshold)
        self._object_interval = max(5.0, float(object_interval))
        self._frames: deque = deque(maxlen=int(frame_history))
        self._gray_prev: Any = None
        self._motion_active = False
        self._last_object_check = 0.0
        self._exposures = 0
        self._humans_detected = 0
        self._last_humans = 0

    # ── Disponibilidade ──────────────────────────────────────

    @property
    def available(self) -> bool:
        return HAS_CV2 and self._probe()

    def _probe(self) -> bool:
        """Abre e fecha a câmera rapidamente (teste inofensivo)."""
        if not HAS_CV2:
            return False
        try:
            cap = cv2.VideoCapture(self._capture_index)
            ok = cap.isOpened()
            cap.release()
            return bool(ok)
        except Exception:
            return False

    # ── Captura ──────────────────────────────────────────────

    def capture(self) -> Any | None:
        """Captura um frame e o guarda no histórico (limitado)."""
        if not HAS_CV2:
            return None
        try:
            cap = cv2.VideoCapture(self._capture_index)
            ok, frame = cap.read()
            cap.release()
            if not ok or frame is None:
                return None
        except Exception as e:
            self._last_error = str(e)
            return None
        self._exposures += 1
        small = cv2.resize(frame, (_FRAME_W, _FRAME_H))
        self._frames.append(small)
        return small

    # ── Detecção de movimento ────────────────────────────────

    def _detect_motion(self, gray) -> bool:
        if not HAS_NUMPY:
            return False
        if self._gray_prev is None:
            self._gray_prev = gray
            return False
        diff = np.abs(gray.astype(int) - self._gray_prev.astype(int))
        fraction = float(np.mean(diff > 25))
        self._gray_prev = gray
        return fraction >= self._motion_threshold

    # ── Detecção de pessoas (HOG padrão do OpenCV) ───────────

    def _detect_humans(self, gray) -> int:
        if not HAS_CV2:
            return 0
        try:
            hog = cv2.HOGDescriptor_getDefaultPeopleDetector()
            if hog is None:
                hog = cv2.HOGDescriptor()
            else:
                detector = cv2.HOGDescriptor()
                detector.setSVMDetector(hog)
                hog = detector
            _, rects = hog.detectMultiScale(gray, winStride=(8, 8))
            self._humans_detected += len(rects)
            return int(len(rects))
        except Exception:
            return 0

    # ── Leitura ──────────────────────────────────────────────

    def sense(self) -> list[Event]:
        if not HAS_CV2 or not HAS_NUMPY or not self._enabled:
            return []
        frame = self.capture()
        if frame is None:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        events: list[Event] = []

        # Movimento: só emite na transição início/fim.
        moving = self._detect_motion(gray)
        if moving and not self._motion_active:
            self._motion_active = True
            events.append(self._make_event(
                EVENT_CAMERA,
                {"detection": "motion", "action": "started",
                 "text": "Movimento detectado pela câmera"},
                priority=PRIORITY_HIGH,
                confidence=0.7,
            ))
        elif not moving and self._motion_active:
            self._motion_active = False
            events.append(self._make_event(
                EVENT_CAMERA,
                {"detection": "motion", "action": "ended",
                 "text": "Movimento na câmera cessou"},
                priority=PRIORITY_NORMAL,
                confidence=0.7,
            ))

        # Pessoas: com taxa limitada e apenas se houver detecção.
        now = self._elapsed()
        if now - self._last_object_check >= self._object_interval:
            self._last_object_check = now
            humans = self._detect_humans(gray)
            if humans > 0:
                self._last_humans = humans
                events.append(self._make_event(
                    EVENT_CAMERA,
                    {"detection": "person", "count": humans,
                     "text": f"Detectada(s) {humans} pessoa(s)"},
                    priority=PRIORITY_HIGH,
                    confidence=0.5,
                ))

        return events

    def _elapsed(self) -> float:
        import time

        return time.monotonic()

    def test_frame(self, gray) -> list[Event]:
        """Força a leitura com um frame fornecido (testes)."""
        if not HAS_NUMPY:
            return []
        events: list[Event] = []
        moving = self._detect_motion(gray)
        if moving and not self._motion_active:
            self._motion_active = True
            events.append(self._make_event(
                EVENT_CAMERA,
                {"detection": "motion", "action": "started",
                 "text": "Movimento detectado pela câmera"},
                priority=PRIORITY_HIGH, confidence=0.7,
            ))
        return events

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data.update({
            "frames_stored": len(self._frames),
            "exposures": self._exposures,
            "motion_active": self._motion_active,
            "humans_detected": self._humans_detected,
            "last_humans": self._last_humans,
        })
        return data
