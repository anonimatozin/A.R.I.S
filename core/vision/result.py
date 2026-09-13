"""Estruturas de resultado do Vision Engine do A.R.I.S.

Uma análise visual é representada por ``VisionResult``, que agrega os
resultados do OCR (texto com posição) e do VLM (descrição da imagem),
além de metadados (janela ativa, erros detectados, confiança).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OcrWord:
    """Uma palavra detectada pelo OCR, com posição e confiança."""

    text: str
    confidence: float = 0.0
    bbox: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "bbox": dict(self.bbox),
        }


@dataclass
class OcrResult:
    """Resultado estruturado da extração de texto da tela."""

    available: bool
    text: str = ""
    lines: list[str] = field(default_factory=list)
    words: list[OcrWord] = field(default_factory=list)
    confidence: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "text": self.text,
            "lines": list(self.lines),
            "words": [w.to_dict() for w in self.words],
            "confidence": round(self.confidence, 3),
            "note": self.note,
        }


@dataclass
class VisionAnalysis:
    """Resultado da análise da imagem inteira (VLM)."""

    available: bool
    description: str = ""
    important_elements: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "description": self.description,
            "important_elements": list(self.important_elements),
            "objects": list(self.objects),
            "note": self.note,
        }


@dataclass
class VisionResult:
    """Resultado completo de uma análise visual da tela."""

    source: str = "screen"
    timestamp: str = ""
    active_application: str = ""
    ocr: OcrResult = field(default_factory=lambda: OcrResult(available=False))
    vision: VisionAnalysis = field(default_factory=lambda: VisionAnalysis(available=False))
    errors_detected: list[str] = field(default_factory=list)
    confidence: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "timestamp": self.timestamp,
            "active_application": self.active_application,
            "ocr": self.ocr.to_dict(),
            "vision": self.vision.to_dict(),
            "errors_detected": list(self.errors_detected),
            "confidence": round(self.confidence, 3),
            "note": self.note,
        }
