"""Fontes visuais do A.R.I.S.

Uma ``VisionSource`` abstrai um dispositivo que produz imagens
(PIL.Image). Toda fonte precisa informar se está disponível e reportar
seu status — sem exceções para o chamador.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

try:  # pragma: no cover - dependência opcional
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]


class VisionSource(ABC):
    """Contrato de uma fonte de captura visual."""

    name: str = "source"

    def __init__(self, logger: Any = None) -> None:
        self._logger = logger

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Indica se a fonte pode capturar neste momento."""

    @abstractmethod
    def capture(self, **kwargs: Any) -> Image.Image | None:
        """Captura uma imagem (retorna None caso falhe)."""

    def get_status(self) -> dict[str, Any]:
        """Status descritivo (para relatórios [VISION])."""
        return {"name": self.name, "available": self.is_available}  # type: ignore[union-attr]

    def _log(self, level: str, message: str) -> None:
        if self._logger is not None:
            getattr(self._logger, level, print)(f"[VISION/{self.name}] {message}")
