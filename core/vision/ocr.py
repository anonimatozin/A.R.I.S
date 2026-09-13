"""Motor OCR do A.R.I.S. — texto estruturado da tela via Tesseract.

Reutiliza a localização do binário do ``modules.desktop_awareness``
(o ``pytesseract`` já instalado) e devolve um resultado estruturado:
texto puro, linhas e palavras com bounding box e confiança.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Any

from core.vision.result import OcrResult, OcrWord

try:  # pragma: no cover - dependência opcional
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

try:  # pragma: no cover - dependência opcional
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None  # type: ignore[assignment]

try:
    from modules.desktop_awareness import _find_tesseract

    _FIND_TESSERACT = True
except Exception:  # pragma: no cover
    _find_tesseract = None  # type: ignore[assignment]
    _FIND_TESSERACT = False

_EXE_CANDIDATES = (
    "tesseract",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
)


class TesseractEngine:
    """Encapsula o pytesseract com detecção robusta do binário."""

    def __init__(self, lang: str = "eng+por", logger: Any = None) -> None:
        self._lang = lang
        self._logger = logger
        self._lock = threading.Lock()
        self._checked = False

    @property
    def available(self) -> bool:
        """True se o binário do Tesseract foi localizado."""
        if pytesseract is None or Image is None:
            return False
        if not self._checked:
            with self._lock:
                if not self._checked:
                    self._locate_binary()
                    self._checked = True
        return bool(_tesseract_path())

    def _locate_binary(self) -> None:
        if pytesseract is None:
            return
        if _find_tesseract is not None:
            try:
                path = _find_tesseract()
                if path:
                    pytesseract.pytesseract.tesseract_cmd = path
                    _set_tesseract_path(path)
                    return
            except Exception:
                pass
        for candidate in _EXE_CANDIDATES:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    pytesseract.pytesseract.tesseract_cmd = candidate
                    _set_tesseract_path(candidate)
                    return
            except Exception:
                continue

    def _image_to_data(self, image: Image.Image) -> dict[str, list]:
        """Chamada real ao pytesseract (isolada para testes)."""
        return pytesseract.image_to_data(  # type: ignore[union-attr]
            image,
            lang=self._lang,
            output_type=pytesseract.Output.DICT,  # type: ignore[union-attr]
        )

    def extract(self, image: Image.Image) -> OcrResult:
        """Extrai palavras/linhas/texto da imagem via Tesseract."""
        if not self.available or image is None:
            note = "OCR indisponível" if pytesseract is None else "Tesseract não localizado"
            return OcrResult(available=False, note=note)
        try:
            data = self._image_to_data(image)
        except Exception as exc:
            self._log("warning", f"OCR com erro: {exc}")
            return OcrResult(available=False, note="falha interna do OCR")

        words: list[OcrWord] = []
        lines: list[str] = []
        current_line = -1
        line_parts: list[str] = []
        total_conf = 0.0
        counted = 0

        n = len(data.get("text", []))
        for i in range(n):
            text = str(data.get("text", [""])[i] or "").strip()
            if not text:
                continue
            conf = _safe_float(data.get("conf", [0])[i])
            total_conf += conf
            counted += 1
            left = int(data.get("left", [0])[i] or 0)
            top = int(data.get("top", [0])[i] or 0)
            width = int(data.get("width", [0])[i] or 0)
            height = int(data.get("height", [0])[i] or 0)
            words.append(
                OcrWord(
                    text=text,
                    confidence=conf / 100.0,
                    bbox={
                        "x": left,
                        "y": top,
                        "width": width,
                        "height": height,
                        "x1": left,
                        "y1": top,
                        "x2": left + width,
                        "y2": top + height,
                    },
                )
            )
            line_num = int(data.get("line_num", [0])[i] or 0)
            if line_num != current_line:
                if line_parts:
                    lines.append(" ".join(line_parts))
                line_parts = [text]
                current_line = line_num
            else:
                line_parts.append(text)
        if line_parts:
            lines.append(" ".join(line_parts))

        confidence = (total_conf / counted) / 100.0 if counted else 0.0
        text = " ".join(w.text for w in words)
        if text:
            self._log("info", "Texto extraído da tela via OCR.")
        else:
            self._log("info", "Nenhum texto detectado na captura.")
        return OcrResult(
            available=True,
            text=text,
            lines=lines,
            words=words,
            confidence=round(confidence, 3),
        )

    def extract_from_path(self, path: str) -> OcrResult:
        try:
            image = Image.open(path)  # type: ignore[union-attr]
        except Exception:
            return OcrResult(available=False, note="imagem não pôde ser aberta")
        return self.extract(image)

    def get_status(self) -> dict[str, Any]:
        return {"available": self.available, "lang": self._lang, "engine": "tesseract"}

    def _log(self, level: str, message: str) -> None:
        if self._logger is not None:
            getattr(self._logger, level, print)(f"[VISION] {message}")


def _safe_float(value: Any) -> float:
    try:
        value = float(value)
        return -1.0 if value < 0 else value
    except (TypeError, ValueError):
        return 0.0


_tesseract = {"bin": None}


def _tesseract_path() -> str | None:
    return _tesseract["bin"]


def _set_tesseract_path(path: str) -> None:
    _tesseract["bin"] = path
