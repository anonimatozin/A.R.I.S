"""Fontes visuais do A.R.I.S. (tela e câmera)."""

from core.vision.sources.base import VisionSource
from core.vision.sources.camera_source import CameraSource
from core.vision.sources.screen_source import ScreenSource

__all__ = ["VisionSource", "CameraSource", "ScreenSource"]
