"""Modelo de visão (VLM) do A.R.I.S.

Analisa a imagem inteira (diferente do OCR). Prioriza o Ollama local
(descobrindo modelos com visão via ``/api/tags``) e oferece Gemini como
fallback remoto. NENHUMA chamada lança exceções para fora — sem modelo
compatível, `ask` retorna None e o sistema informa a limitação.
"""

from __future__ import annotations

import base64
import io
import os
import threading
import time
from typing import Any

from core.vision.result import VisionAnalysis

try:  # pragma: no cover - dependência opcional
    import requests

    HAS_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]
    HAS_REQUESTS = False

try:  # pragma: no cover - dependência opcional
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

try:
    from core.rate_limiter import gemini_limiter, ollama_limiter
except Exception:  # pragma: no cover
    gemini_limiter = None  # type: ignore[assignment]
    ollama_limiter = None  # type: ignore[assignment]

#: Nomes que indicam capacidade de visão (aplicados a nomes de modelos).
_VISION_HINTS = (
    "llava", "vision", "vlm", "vl", "moondream", "minicpm", "gemma3",
    "bakllava", "internvl", "qwen2-vl", "qwen2.5-vl", "qwen2.5distilled-vl",
    "llama3.2-vision", "phi3-vision", "granite-vision", "idefics", "fuyu",
    "cogvlm", "florence", "xcomposer", "opencode",
)
#: Modelos razoáveis que não contém os hints acima, mas são de visão.
_EXTRA_VISION_MODELS = (
    "minicpm-v",
    "granite3.2-vision",
    "gemma3v",
)


def _to_data_uri(image: Image.Image) -> str:
    """Converte uma imagem PIL para data URI base64 (ideal para VLM)."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _is_vision_model(name: str) -> bool:
    lower = name.strip().lower()
    return any(hint in lower for hint in _VISION_HINTS) or lower in _EXTRA_VISION_MODELS


class _LoggedMixin:
    """Mixin that provides a simple _log method using the instance's logger."""

    def _log(self, level: str, message: str) -> None:
        if getattr(self, "_logger", None) is not None:
            getattr(self._logger, level, print)(f"[VISION] {message}")


class OllamaVision(_LoggedMixin):
    """Cliente Ollama (texto+imagem). Descobre o modelo de visão sozinho."""

    _TAGS_TTL = 60.0

    def __init__(self, base_url: str, model: str = "", timeout: float = 30.0, logger: Any = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._configured_model = model.strip()
        self._timeout = timeout
        self._logger = logger
        self._tags_cache: list[str] = []
        self._tags_at = 0.0
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return HAS_REQUESTS and self._model() is not None

    def _fetch_tags(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._tags_cache and (now - self._tags_at) < self._TAGS_TTL:
                return
            try:
                response = requests.get(  # type: ignore[union-attr]
                    f"{self._base_url}/api/tags", timeout=self._timeout
                )
                if response.status_code != 200:
                    raise ValueError(f"HTTP {response.status_code}")
                models = [m.get("name", "") for m in response.json().get("models", [])]
                self._tags_cache = [
                    m.split(":")[0] if ":" in m and not m[0].isdigit() else m
                    for m in models
                ]
                self._tags_at = now
            except Exception:
                self._tags_cache = []
                self._tags_at = now

    def _model(self) -> str | None:
        if self._configured_model:
            return self._configured_model
        self._fetch_tags()
        for name in self._tags_cache:
            if _is_vision_model(name):
                return name
        return None

    def ask(self, image: Image.Image, question: str) -> str | None:
        model = self._model()
        if model is None:
            return None
        if ollama_limiter is not None:
            ollama_limiter.wait_if_needed()
        try:
            response = requests.post(  # type: ignore[union-attr]
                f"{self._base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": question,
                    "images": [_to_data_uri(image)],
                    "stream": False,
                    "options": {"temperature": 0.1},
                    "keep_alive": "5m",
                },
                timeout=self._timeout,
            )
            if response.status_code != 200:
                self._log("warning", f"Ollama respondeu HTTP {response.status_code}")
                return None
            return str(response.json().get("response", "")).strip() or None
        except Exception as exc:
            self._log("warning", f"Ollama indisponível: {exc}")
            return None


class GeminiVision:
    """Cliente Gemini (OpenAI-compatible) para imagem + texto."""

    def __init__(
        self,
        model: str = "gemini-3.6-flash",
        api_key: str = "",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/",
        timeout: float = 30.0,
        logger: Any = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._logger = logger
        self._openai_client: Any = None

    def _log(self, level: str, message: str) -> None:
        if self._logger is not None:
            getattr(self._logger, level, print)(f"[VISION] {message}")

    @property
    def available(self) -> bool:
        if not self._api_key:
            return False
        return self._get_client() is not None

    def _get_client(self) -> Any:
        if self._openai_client is None:
            try:
                from openai import OpenAI

                self._openai_client = OpenAI(
                    api_key=self._api_key,
                    base_url=self._base_url,
                    timeout=self._timeout,
                )
            except Exception as exc:
                self._log("warning", f"Falha ao criar cliente Gemini: {exc}")
                self._openai_client = False  # type: ignore[assignment]
        return self._openai_client if self._openai_client is not False else None

    def ask(self, image: Image.Image, question: str) -> str | None:
        client = self._get_client()
        if client is None:
            return None
        if gemini_limiter is not None:
            gemini_limiter.wait_if_needed()
        try:
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {"type": "image_url", "image_url": {"url": _to_data_uri(image)}},
                        ],
                    }
                ],
                max_tokens=512,
            )
            if not response.choices:
                return None
            return str(response.choices[0].message.content).strip() or None
        except Exception as exc:
            self._log("warning", f"Gemini indisponível: {exc}")
            return None


class VisionLanguageModel:
    """Facade do VLM — escolhe provider e NUNCA lança para o chamador."""

    def __init__(self, config: Any, logger: Any = None) -> None:
        self._config = config
        self._logger = logger
        self._providers: dict[str, Any] = {
            "ollama": OllamaVision(
                config.ollama_base_url,
                model=config.vlm_model,
                timeout=config.vision_timeout,
                logger=logger,
            ),
            "google": GeminiVision(
                model=config.vlm_model or "gemini-3.6-flash",
                api_key=os.getenv("GEMINI_API_KEY", ""),
                timeout=config.vision_timeout,
                logger=logger,
            ),
        }
        self._preferred = config.vlm_provider

    def _log(self, level: str, message: str) -> None:
        if getattr(self, "_logger", None) is not None:
            getattr(self._logger, level, print)(f"[VISION] {message}")

    def ask(self, image: Image.Image, question: str) -> str | None:
        if not self._config.vlm_enabled or image is None:
            return None
        ordered = [self._preferred] if self._preferred in self._providers else []
        ordered += [name for name in self._providers if name not in ordered]
        for name in ordered:
            provider = self._providers[name]
            try:
                answer = provider.ask(image, question)
                if answer:
                    return answer
            except Exception as exc:
                self._log("warning", f"VLM {name} falhou: {exc}")
                continue
        self._log("info", "VLM indisponível no momento (nenhum modelo de visão ativo).")
        return None

    def is_available(self) -> bool:
        return any(p.available for p in self._providers.values())

    def analyze(self, image: Image.Image, question: str) -> VisionAnalysis:
        answer = self.ask(image, question)
        if not answer:
            return VisionAnalysis(available=False, note="modelo de visão indisponível")
        return VisionAnalysis(available=True, description=answer)

    def get_status(self) -> dict[str, Any]:
        return {
            "provider": self._preferred,
            "providers": {name: bool(p.available) for name, p in self._providers.items()},
            "available": self.is_available(),
        }



