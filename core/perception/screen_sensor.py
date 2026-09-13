"""Sensor de tela do A.R.I.S.

Observa a mudança da janela em foco (Windows) e, opcionalmente, extrai
texto da tela via OCR (pesado, desligado por padrão).

Reutiliza o ``DesktopAwareness`` existente quando disponível. Sem
``pyautogui``/``PIL``, fica ``offline`` e emite zero eventos.
"""

from __future__ import annotations

import ctypes
import time
from typing import Any

from core.neural.events import EVENT_SCREEN_CHANGED, PRIORITY_LOW, PRIORITY_NORMAL, Event
from core.perception.sensor import Sensor
from utils.logger import Logger

_WIN_CAPABLE = hasattr(ctypes, "windll")


class ScreenSensor(Sensor):
    """Sensor de mudança de tela (janela ativa + OCR opcional)."""

    name = "screen"

    def __init__(
        self,
        event_bus=None,
        enabled: bool = True,
        interval: float = 5.0,
        logger: Logger | None = None,
        awareness=None,
        ocr_enabled: bool = False,
        ocr_interval: float = 120.0,
    ) -> None:
        super().__init__(event_bus=event_bus, enabled=enabled, interval=interval, logger=logger)
        self._awareness = awareness
        self._ocr_enabled = bool(ocr_enabled)
        self._ocr_interval = max(10.0, float(ocr_interval))
        self._window = ""
        self._last_ocr_text = ""
        self._last_ocr_at = 0.0
        self._window_changes = 0

    @property
    def available(self) -> bool:
        if self._awareness is None:
            return _WIN_CAPABLE
        available = bool(getattr(self._awareness, "available", False))
        return available or _WIN_CAPABLE

    # ── Janela ativa (Windows) ───────────────────────────────

    def _active_window(self) -> str:
        if not _WIN_CAPABLE:
            return ""
        try:
            ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
            handle = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(handle)
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(handle, buffer, length + 1)
            return buffer.value
        except Exception:
            return ""

    def _ocr_text(self) -> str:
        if self._awareness is None or not getattr(self._awareness, "ocr_available", False):
            return ""
        try:
            text = self._awareness.extract_text_from_screen()
            return str(text).strip() if not str(text).startswith("Erro") else self._last_ocr_text
        except Exception:
            return self._last_ocr_text

    # ── Leitura ──────────────────────────────────────────────

    def sense(self) -> list[Event]:
        if not self._enabled:
            return []
        events: list[Event] = []

        window = self._active_window()
        if window and window != self._window:
            self._window_changes += 1
            self._window = window
            events.append(self._make_event(
                EVENT_SCREEN_CHANGED,
                {"window": window, "text": f"Janela ativa: {window}"},
                priority=PRIORITY_LOW,
                confidence=0.7,
            ))

        now = time.monotonic()
        if self._ocr_enabled and now - self._last_ocr_at >= self._ocr_interval:
            self._last_ocr_at = now
            text = self._ocr_text()
            if text and text != self._last_ocr_text:
                self._last_ocr_text = text
                events.append(self._make_event(
                    EVENT_SCREEN_CHANGED,
                    {"window": window, "text": text[:500]},
                    priority=PRIORITY_NORMAL,
                    confidence=0.5,
                ))

        return events

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data.update({
            "window": self._window,
            "window_changes": self._window_changes,
            "ocr_enabled": self._ocr_enabled,
            "ocr_text": self._last_ocr_text[:80],
        })
        return data
