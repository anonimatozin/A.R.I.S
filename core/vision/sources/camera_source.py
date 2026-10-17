"""Fonte visual: câmera (preparada, sem hardware).

Hoje não há câmera/OpenCV instalados — `is_available` retorna False e a
ARIS reporta a informação com honestidade. O contrato de captura já fica
definido para uma futura integração (espelha `core/perception/camera_sensor.py`).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

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

    def __init__(
        self,
        enabled: bool = False,
        logger: Any = None,
        capture_index: int = 0,
        fps: float = 1.0,
    ) -> None:
        super().__init__(logger=logger)
        self._enabled = enabled
        self._capture_index = capture_index
        self._target_fps = max(0.1, min(fps, 30.0))
        self._min_interval = 1.0 / self._target_fps

        # Continuous capture state
        self._capture_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._latest_frame: Optional[Image.Image] = None
        self._frame_lock = threading.Lock()
        self._last_capture_time = 0.0

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

    @property
    def is_capturing(self) -> bool:
        return self._capture_thread is not None and self._capture_thread.is_alive()

    @property
    def current_fps(self) -> float:
        if self._last_capture_time == 0:
            return 0.0
        return 1.0 / max(time.time() - self._last_capture_time, 1e-6)

    def start_continuous_capture(self) -> bool:
        """Inicia captura contínua em thread separada (1-2 fps por padrão)."""
        if not self.is_available:
            self._log("info", "Não pode iniciar captura: câmera indisponível.")
            return False
        if self.is_capturing:
            self._log("info", "Captura contínua já está rodando.")
            return True

        self._stop_event.clear()
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="camera-continuous",
            daemon=True,
        )
        self._capture_thread.start()
        self._log("info", f"Captura contínua iniciada a {self._target_fps:.1f} fps")
        return True

    def stop_continuous_capture(self) -> None:
        """Para a captura contínua."""
        if self._capture_thread is not None:
            self._stop_event.set()
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
            self._log("info", "Captura contínua parada.")

    def _capture_loop(self) -> None:
        """Loop de captura contínua com throttling por FPS."""
        cap = None
        try:
            cap = cv2.VideoCapture(self._capture_index)  # type: ignore[union-attr]
            if not cap or not cap.isOpened():
                self._log("warning", "Não foi possível abrir a câmera no loop contínuo.")
                return

            while not self._stop_event.is_set():
                start = time.time()

                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(self._min_interval)
                    continue

                try:
                    pil_image = Image.fromarray(
                        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    )
                except Exception as exc:
                    self._log("warning", f"Falha ao converter frame: {exc}")
                    time.sleep(self._min_interval)
                    continue

                with self._frame_lock:
                    self._latest_frame = pil_image
                    self._last_capture_time = time.time()

                # Throttle para manter FPS alvo
                elapsed = time.time() - start
                sleep_time = max(0.0, self._min_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception as exc:
            self._log("warning", f"Erro no loop de captura: {exc}")
        finally:
            if cap is not None:
                cap.release()
            with self._frame_lock:
                self._latest_frame = None

    def get_latest_frame(self) -> Optional[Image.Image]:
        """Retorna o frame mais recente (não bloqueante)."""
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame else None

    def capture(self, **kwargs: Any) -> Image.Image | None:
        if not self.is_available:
            self._log("info", "Câmera indisponível: sem hardware atual.")
            return None

        # Se captura contínua ativa, retorna frame mais recente (não bloqueante)
        if self.is_capturing:
            frame = self.get_latest_frame()
            if frame:
                return frame

        # Fallback: captura única síncrona
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
            "continuous_capture": self.is_capturing,
            "target_fps": self._target_fps,
            "current_fps": round(self.current_fps, 2),
            "reason": "sem hardware atual" if self._enabled and not probe else "câmera desabilitada",
        }
