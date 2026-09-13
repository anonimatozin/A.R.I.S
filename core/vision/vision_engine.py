"""Vision Engine do A.R.I.S.

Facade que orquestra captura → OCR → VLM → resultado estruturado, e
conecta o resultado ao restante do sistema (Event Bus, atenção,
contexto e memória episódica).

A visão é sob demanda: só executa quando chamada (nunca contínua). Níveis
de fallback são 100% seguros — captura/OCR/VLM indisponíveis nunca
causam falha no chamador.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from core.neural.events import (
    EVENT_VISION_APPLICATION_DETECTED,
    EVENT_VISION_ERROR_DETECTED,
    EVENT_VISION_OBJECT_DETECTED,
    EVENT_VISION_SCREEN_ANALYZED,
    EVENT_VISION_TEXT_DETECTED,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    Event,
)
from core.vision.config import VisionConfig
from core.vision.ocr import TesseractEngine
from core.vision.result import OcrResult, VisionAnalysis, VisionResult
from core.vision.sources.camera_source import CameraSource
from core.vision.sources.screen_source import ScreenSource
from core.vision.vlm import VisionLanguageModel

try:  # pragma: no cover
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

_DEFAULT_QUESTION = (
    "Descreva os elementos importantes desta tela: janelas, botões, "
    "ícones, menus e mensagens de erro. Responda em português."
)


class VisionEngine:
    """Motor de visão computacional da ARIS."""

    def __init__(
        self,
        event_bus: Any = None,
        awareness: Any = None,
        logger: Any = None,
        config: VisionConfig | None = None,
        memory: Any = None,
    ) -> None:
        self._config = config or VisionConfig.load()
        self._logger = logger
        self._bus = event_bus
        self._screen = ScreenSource(awareness=awareness, logger=logger)
        self._camera = CameraSource(enabled=self._config.camera_enabled, logger=logger)
        self._ocr = TesseractEngine(logger=logger)
        self._vlm = VisionLanguageModel(self._config, logger=logger)
        self._memory = memory
        self._lock = threading.Lock()

    # ------------------------------------------------------------- dependecias --#
    @property
    def ocr(self) -> TesseractEngine:
        return self._ocr

    @property
    def vlm(self) -> VisionLanguageModel:
        return self._vlm

    @property
    def screen(self) -> ScreenSource:
        return self._screen

    # ------------------------------------------------------------------ captura --#
    def capture_image(self, monitor: dict[str, Any] | None = None) -> Image.Image | None:
        """Captura a tela sob demanda (None se a tela estiver indisponível)."""
        if not self._config.screen_enabled:
            self._log("info", "Captura de tela desabilitada no momento.")
            return None
        self._log("info", "Tela sendo capturada (sob demanda).")
        try:
            image = self._screen.capture(monitor)
        except Exception as exc:
            self._log("warning", f"Falha ao capturar a tela: {exc}")
            return None
        if image is None:
            self._log("warning", "Tela indisponível para captura.")
        return image

    def _screenshot_dir(self) -> Path:
        if self._config.save_dir:
            return Path(self._config.save_dir)
        return Path(__file__).resolve().parents[2] / "data" / "screenshots"

    def save_image(self, image: Image.Image) -> str | None:
        """Salva a captura (apenas se ARIS_VISION_SAVE_IMAGES=True)."""
        if not self._config.save_images:
            return None
        try:
            directory = self._screenshot_dir()
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"vision_{datetime.now():%Y%m%d_%H%M%S}.png"
            image.save(path, format="PNG")
            return str(path)
        except Exception as exc:
            self._log("warning", f"Não foi possível salvar a captura: {exc}")
            return None

    def _resize(self, image: Image.Image) -> Image.Image:
        """Reduz o maior lado para ARIS_VISION_MAX_IMAGE_SIZE antes do VLM."""
        try:
            max_side = max(self._config.max_image_size, 128)
            if max(image.size) <= max_side:
                return image
            ratio = max_side / max(image.size)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            return image.copy().resize(new_size, getattr(Image, "Resampling", Image).LANCZOS)
        except Exception:
            return image

    # ------------------------------------------------------------ pipeline OCR --#
    def extract_text(self, monitor: dict[str, Any] | None = None) -> str:
        """OCR rápido: retorna apenas o texto da tela."""
        return self.read_screen(monitor=monitor).text

    def read_screen(self, monitor: dict[str, Any] | None = None) -> OcrResult:
        image = self.capture_image(monitor)
        if image is None:
            return OcrResult(available=False, note="tela indisponível para captura")
        if not self._config.ocr_enabled or not self._ocr.available:
            return OcrResult(
                available=False,
                note="OCR desabilitado" if not self._config.ocr_enabled else "Tesseract não localizado",
            )
        try:
            result = self._ocr.extract(image)
        except Exception as exc:
            self._log("warning", f"OCR com erro: {exc}")
            return OcrResult(available=False, note="falha interna do OCR")
        if result.text:
            self._publish(EVENT_VISION_TEXT_DETECTED, result.text, result.confidence, PRIORITY_LOW)
        return result

    # ------------------------------------------------------------- pipeline VLM --#
    def ask(self, question: str, monitor: dict[str, Any] | None = None) -> str | None:
        """Pergunta sobre a imagem atual ao VLM (None se indisponível)."""
        if not self._config.vlm_enabled:
            self._log("info", "Análise de imagem (VLM) desabilitada.")
            return None
        image = self.capture_image(monitor)
        if image is None:
            return None
        self._log("info", "Enviando imagem ao modelo de visão...")
        try:
            answer = self._vlm.ask(self._resize(image), question or _DEFAULT_QUESTION)
        except Exception as exc:
            self._log("warning", f"VLM com erro: {exc}")
            return None
        if answer:
            self._publish(EVENT_VISION_OBJECT_DETECTED, answer[:220], 0.6, PRIORITY_LOW)
        return answer

    # ----------------------------------------------------------- pipeline geral --#
    def analyze_screen(
        self,
        question: str | None = None,
        monitor: dict[str, Any] | None = None,
        include_vlm: bool = True,
    ) -> VisionResult:
        """Pipeline completo: captura → OCR → VLM → erros → resultado."""
        with self._lock:
            timestamp = datetime.now().isoformat(timespec="seconds")
            self._log("info", "Tela sendo analisada.")
            image = self.capture_image(monitor)
            if image is None:
                result = VisionResult(
                    source="screen",
                    timestamp=timestamp,
                    note="Não foi possível capturar a tela.",
                )
                self._publish(EVENT_VISION_SCREEN_ANALYZED, result, 0.3, PRIORITY_LOW)
                return result

            if self._config.save_images:
                saved = self.save_image(image)
                if saved:
                    self._log("info", f"Captura salva em {saved}")

            application = self._screen.get_active_window().get("title", "")

            ocr_result: OcrResult = OcrResult(available=False)
            if self._config.ocr_enabled and self._ocr.available:
                try:
                    ocr_result = self._ocr.extract(image)
                except Exception as exc:
                    self._log("warning", f"OCR com erro: {exc}")

            vision_result: VisionAnalysis = VisionAnalysis(available=False)
            if include_vlm and self._config.vlm_enabled:
                answer = self._vlm.ask(self._resize(image), question or _DEFAULT_QUESTION)
                if answer:
                    vision_result = VisionAnalysis(available=True, description=answer)

            errors = self._detect_errors(ocr_result.text)
            confidence = self._compute_confidence(ocr_result.confidence, application, vision_result.available)

            result = VisionResult(
                source=self._config.vlm_provider if vision_result.available else "screen",
                timestamp=timestamp,
                active_application=application,
                ocr=ocr_result,
                vision=vision_result,
                errors_detected=errors,
                confidence=round(confidence, 3),
            )
            self._publish_analysis(result)
            if errors:
                self._publish(
                    EVENT_VISION_ERROR_DETECTED,
                    "Erro detectado na tela: " + ", ".join(errors),
                    0.8,
                    PRIORITY_HIGH,
                )
                self._record_error_memory(errors, ocr_result.text, application)
            return result

    # ------------------------------------------------------------- helpers API --#
    def describe_screen(self, question: str | None = None) -> dict[str, Any]:
        """Descrição amigável da tela (dict pronto para relatórios)."""
        if not self._config.screen_enabled:
            return {
                "available": False,
                "reason": "Captura de tela desabilitada. Defina ARIS_SCREEN_VISION_ENABLED=true.",
            }
        result = self.analyze_screen(question=question)
        return {
            "available": True,
            "active_application": result.active_application,
            "text": result.ocr.text,
            "vision": result.vision.description,
            "errors_detected": result.errors_detected,
            "timestamp": result.timestamp,
        }

    def find_on_screen(self, query: str, monitor: dict[str, Any] | None = None) -> dict[str, Any]:
        """Procura um texto na tela retornando posição e confiança."""
        ocr = self.read_screen(monitor=monitor)
        if not ocr.available:
            return {"found": False, "reason": ocr.note or "OCR indisponível"}
        if not query:
            return {"found": False, "reason": "busca vazia"}
        needle = query.lower().strip()
        best: Any | None = None
        for word in ocr.words:
            if needle in word.text.lower():
                center = (
                    word.bbox.get("x", 0) + word.bbox.get("width", 0) / 2,
                    word.bbox.get("y", 0) + word.bbox.get("height", 0) / 2,
                )
                if best is None or word.confidence > best[1]:
                    best = (word, center)
        if best is None:
            return {"found": False, "reason": f"texto \"{query}\" não visível na tela"}
        word, center = best
        return {
            "found": True,
            "query": query,
            "text": word.text,
            "position": {"x": center[0], "y": center[1]},
            "confidence": word.confidence,
        }

    def detect_errors(self, monitor: dict[str, Any] | None = None) -> list[str]:
        """Detecta termos de erro nas palavras visíveis (sem acionar VLM)."""
        if not self._config.ocr_enabled:
            return []
        ocr = self.read_screen(monitor=monitor)
        if not ocr.available:
            return []
        return self._detect_errors(ocr.text)

    def _detect_errors(self, text: str) -> list[str]:
        matched: list[str] = []
        if not text:
            return matched
        lower = text.lower()
        for term in self._config.error_terms:
            if term in lower:
                matched.append(term)
        return matched

    def _compute_confidence(
        self, ocr_confidence: float, application: str, vision_available: bool
    ) -> float:
        base = 0.9 if application else 0.5
        if vision_available:
            base += 0.1
        return min(1.0, base + ocr_confidence * 0.1)

    # ------------------------------------------------------------------- status --#
    def camera_available(self) -> bool:
        return self._camera.is_available

    def camera_status(self) -> str:
        status = self._camera.get_status()
        if self._camera.is_available:
            return "Câmera disponível e pronta para capturar a cada solicitação."
        if status.get("hardware_detected"):
            return "Câmera detectada, mas desabilitada (ARIS_VISION_CAMERA_ENABLED=false)."
        return "Câmera não disponível neste dispositivo (sem hardware detectado)."

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self._config.enabled,
            "screen": self._screen.get_status(),
            "camera": self._camera.get_status(),
            "ocr": self._ocr.get_status(),
            "vlm": self._vlm.get_status(),
            "save_images": self._config.save_images,
            "timeout": self._config.vision_timeout,
        }

    def format_status(self) -> str:
        status = self.get_status()
        lines = [
            "[VISION] Sistema de visão computacional",
            f"  Estado geral: {'ativo' if status['enabled'] else 'desativado'}",
            f"  Tela: {'disponível' if status['screen']['available'] else 'não disponível'} ({status['screen'].get('monitors', 1)} monitor(es))",
            f"  Câmera: {'disponível' if status['camera']['available'] else 'não disponível'}",
            f"  OCR (Tesseract): {'ativo' if status['ocr']['available'] else 'não ativo'}",
            f"  VLM ({status['vlm']['provider']}): {'ativo' if status['vlm']['available'] else 'não ativo'}",
            f"  Salvar capturas: {'sim' if status['save_images'] else 'não'} (privacidade)",
        ]
        return "\n".join(lines)

    def summarize_for_speech(self, result: VisionResult) -> str:
        """Resumo curto e falável do resultado (usado pelo handler)."""
        parts: list[str] = []
        if result.active_application:
            parts.append(f"Janela ativa: {result.active_application}.")
        if result.vision.available and result.vision.description:
            parts.append(_clip(result.vision.description, 220))
        elif result.ocr.available and result.ocr.text:
            parts.append(f"Texto visível: {_clip(result.ocr.text, 220)}.")
        else:
            if result.ocr.available and not result.ocr.text:
                parts.append("Não foi possível ler texto na tela (OCR sem conteúdo).")
            else:
                parts.append("Sem texto detectável e sem modelo de visão ativo no momento.")
        if result.errors_detected:
            parts.append("Possíveis erros detectados: " + ", ".join(result.errors_detected) + ".")
        return " ".join(parts)

    # ------------------------------------------------------------- eventos/mem --#
    def _publish(self, event_type: str, text: str, confidence: float, priority: int) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(
                Event(
                    event_type=event_type,
                    source="vision",
                    priority=priority,
                    confidence=confidence,
                    payload={"text": _clip(text, 200), "source": "screen"},
                )
            )
        except Exception as exc:
            self._log("warning", f"Falha ao publicar evento {event_type}: {exc}")

    def _publish_analysis(self, result: VisionResult) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(
                Event(
                    event_type=EVENT_VISION_SCREEN_ANALYZED,
                    source="vision",
                    priority=PRIORITY_LOW,
                    confidence=result.confidence,
                    payload={
                        "text": _clip(
                            result.vision.description
                            or result.ocr.text
                            or (result.active_application or result.note),
                            200,
                        ),
                        "application": result.active_application,
                        "errors": result.errors_detected,
                        "source": "screen",
                    },
                )
            )
            if result.active_application:
                self._bus.publish(
                    Event(
                        event_type=EVENT_VISION_APPLICATION_DETECTED,
                        source="vision",
                        priority=PRIORITY_LOW,
                        confidence=0.9,
                        payload={"text": result.active_application, "source": "screen"},
                    )
                )
            if result.ocr.available and result.ocr.text:
                self._bus.publish(
                    Event(
                        event_type=EVENT_VISION_TEXT_DETECTED,
                        source="vision",
                        priority=PRIORITY_LOW,
                        confidence=result.ocr.confidence,
                        payload={"text": _clip(result.ocr.text, 200), "source": "screen"},
                    )
                )
        except Exception as exc:
            self._log("warning", f"Falha ao publicar análise: {exc}")

    def _record_error_memory(self, errors: list[str], context: str, application: str) -> None:
        if self._memory is None:
            return
        try:
            severity = _HIGH_ERROS.get(errors[0].lower(), 6.0) if errors else 6.0
            snippet = context[:240] or f"janela ativa: {application}" or "(sem contexto)"
            remember = getattr(self._memory, "remember", None)
            if remember is None:
                create_episode = getattr(self._memory, "create_episode", None)
                if create_episode is None:
                    return
                create_episode(
                    content=f"Erro detectado na tela: {', '.join(errors)}. Contexto: {snippet}",
                    importance=severity,
                    source="vision",
                )
                return
            remember(
                content=f"Erro detectado na tela: {', '.join(errors)}. Contexto: {snippet}",
                kind="episodic",
                importance=severity,
                source="vision",
                tags=["visao", "erro"],
                summary=f"Erro detectado na tela: {', '.join(errors)}",
            )
        except Exception as exc:
            self._log("warning", f"Falha ao registrar erro na memória: {exc}")

    def _log(self, level: str, message: str) -> None:
        if self._logger is not None:
            getattr(self._logger, level, print)(f"[VISION] {message}")


_HIGH_ERROS = {
    "crash": 7.5,
    "panic": 7.5,
    "exception": 7.0,
    "out of memory": 7.0,
    "fatal": 7.5,
    "erro": 6.5,
    "error": 6.5,
    "not found": 6.0,
}


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
