"""Fonte visual: tela do computador (multi-monitor).

A captura é sob demanda. No Windows, os monitores são enumerados via
``EnumDisplayMonitors`` (coordinates da tela real); em outras
plataformas, usamos o tamanho da tela principal como um único monitor.
"""

from __future__ import annotations

import ctypes
import platform
from typing import Any

from core.vision.sources.base import VisionSource

try:  # pragma: no cover - dependência opcional
    import pyautogui

    _PYAUTOGUI = True
except Exception:  # pragma: no cover
    pyautogui = None  # type: ignore[assignment]
    _PYAUTOGUI = False

try:  # pragma: no cover
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

_WINDOWS = platform.system() == "Windows"


def _list_windows_monitors() -> list[dict[str, int]]:
    """Enumera monitores no Windows via EnumDisplayMonitors."""
    monitors: list[dict[str, int]] = []

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(RECT),
        ctypes.c_double,
    )

    def _cb(monitor: Any, hdc: Any, rect: Any, data: Any) -> bool:
        area = rect.contents if rect else None
        if area is not None:
            monitors.append(
                {
                    "left": int(area.left),
                    "top": int(area.top),
                    "width": int(area.right - area.left),
                    "height": int(area.bottom - area.top),
                }
            )
        return True

    monitor_enum_proc = callback_type(_cb)
    user32 = ctypes.windll.user32
    user32.EnumDisplayMonitors(0, 0, monitor_enum_proc, 0)
    return monitors


class ScreenSource(VisionSource):
    """Captura a tela (ou um monitor específico) como imagem."""

    name = "screen"

    def __init__(self, awareness: Any = None, logger: Any = None) -> None:
        super().__init__(logger=logger)
        self._awareness = awareness

    @property
    def is_available(self) -> bool:
        if not _PYAUTOGUI or Image is None:
            return False
        if self._awareness is not None:
            return bool(getattr(self._awareness, "available", True))
        return True

    def get_active_window(self) -> dict[str, Any]:
        """Informações da janela ativa (melhor esforço)."""
        if self._awareness is not None:
            try:
                info = self._awareness.get_active_window_info()
                if info and info.get("title"):
                    return info
            except Exception:
                pass
        return {"title": "", "window": ""}

    def list_monitors(self) -> list[dict[str, int]]:
        if _WINDOWS and _PYAUTOGUI:
            try:
                monitors = _list_windows_monitors()
                if monitors:
                    return [
                        {"index": i, **m} for i, m in enumerate(monitors)
                    ]
            except Exception:
                pass
        width, height = (1280, 720)
        if _PYAUTOGUI:
            try:
                width, height = pyautogui.size()  # type: ignore[union-attr]
            except Exception:
                pass
        return [{"index": 0, "left": 0, "top": 0, "width": int(width), "height": int(height)}]

    def capture(self, monitor: dict[str, Any] | None = None) -> Image.Image | None:
        if Image is None or not _PYAUTOGUI:
            self._log("warning", "Tela indisponível: pyautogui/PIL ausentes.")
            return None
        try:
            if monitor is not None:
                region = (
                    int(monitor["left"]),
                    int(monitor["top"]),
                    int(monitor["width"]),
                    int(monitor["height"]),
                )
                return pyautogui.screenshot(region=region)  # type: ignore[union-attr]
            return pyautogui.screenshot()  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover
            self._log("warning", f"Falha ao capturar a tela: {exc}")
            return None

    def get_status(self) -> dict[str, Any]:
        monitors = self.list_monitors()
        return {
            "name": self.name,
            "available": self.is_available,
            "monitors": len(monitors),
            "active_application": self.get_active_window().get("title", ""),
        }
