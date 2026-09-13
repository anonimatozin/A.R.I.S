"""Fonte visual: câmera (preparada, sem hardware).

Hoje não há câmera/OpenCV instalados — `is_available` retorna False e a
ARIS reporta a informação com honestidade. O contrato de captura já fica
definido para uma futura integração (espelha `core/perception/camera_sensor.py`).
"""

from __future__ import annotations

from typing import Any

from core.vision.sources.base import VisionSource

try:  # pragma: no cover - dependência opcional
    import cv2

    HAS_CV2 = True
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    HAS_CV2 = False

try:  # pragma: no cover
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

try:  # pragma: no cover - numpy só é necessário com OpenCV
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]


class CameraSource(VisionSource):
    """Câmera via OpenCV (pré-integração — indisponível sem hardware)."""

    name = "camera"

    def __init__(self, enabled: bool = False, logger: Any = None, capture_index: int = 0) -> None:
        super().__init__(logger=logger)
        self._enabled = enabled
        self._capture_index = capture_index

    def _probe(self) -> bool:
        if not HAS_CV2 or Image is None or np is None:
            return False
        try:
            cap = cv2.VideoCapture(self._capture_index)  # type: ignore[union-attr]
            ok = bool(cap and cap.isOpened())
            if cap is not None:
                cap.release()
            return ok
        except Exception:
            return False

    @property
    def is_available(self) -> bool:
        return self._enabled and self._probe()

    def capture(self, **kwargs: Any) -> Image.Image | None:
        if not self.is_available:
            self._log("info", "Câmera indisponível: sem hardware atual.")
            return None
        try:
            cap = cv2.VideoCapture(self._capture_index)  # type: ignore[union-attr]
            ok, frame = cap.read()
            cap.release()
            if not ok or frame is None:
                return None
            return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover
            self._log("warning", f"Falha na captura da câmera: {exc}")
            return None

    def get_status(self) -> dict[str, Any]:
        probe = self._probe()
        return {
            "name": self.name,
            "available": self.is_available,
            "enabled": self._enabled,
            "hardware_detected": probe,
            "reason": "sem hardware atual" if self._enabled and not probe else "câmera desabilitada",
        }
