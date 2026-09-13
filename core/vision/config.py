"""Configuração do Vision Engine do A.R.I.S.

Seguindo o padrão da camada de percepção (``PerceptionConfig``): tudo é
controlado por variáveis de ambiente (prefixo ``ARIS_``) e os defaults
NÃO exigem câmera, OCR ou modelo de visão instalados. Componentes
indisponíveis são reportados e o sistema opera com os níveis de fallback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Termos (em minúsculas) que disparam o sinal de erro na tela (OCR).
DEFAULT_ERROR_TERMS = (
    "erro", "error", "errors", "falha", "falhou", "failed", "exception",
    "crash", "panic", "out of memory", "null pointer", "not found",
    "invalido", "inválido", "invalid", "fatal", "avisar", "contacte",
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class VisionConfig:
    """Configuração da camada de visão computacional.

    Attributes:
        enabled: Liga/desliga o Vision Engine como um todo.
        screen_enabled: Captura de tela on-demand habilitada.
        ocr_enabled: OCR via Tesseract habilitado.
        vlm_enabled: Modelo de visão (VLM) habilitado.
        camera_enabled: Câmera habilitada (default False — sem hardware).
        vlm_provider: Provedor do VLM (``ollama`` ou ``google``).
        vlm_model: Modelo de visão (``""`` = autodetectar em Ollama).
        ollama_base_url: URL base da API do Ollama.
        vision_timeout: Timeout das chamadas de visão (s).
        max_image_size: Maior lado (px) da imagem enviada ao VLM.
        save_images: Salvar capturas em disco (default False).
        save_dir: Diretório para capturas salvas (vazio = data/screenshots).
        error_terms: Termos que disparam detecção de erro no OCR.
    """

    enabled: bool = True
    screen_enabled: bool = True
    ocr_enabled: bool = True
    vlm_enabled: bool = True
    camera_enabled: bool = False
    vlm_provider: str = "ollama"
    vlm_model: str = ""
    ollama_base_url: str = "http://localhost:11434"
    vision_timeout: float = 30.0
    max_image_size: int = 1024
    save_images: bool = False
    save_dir: str = ""
    error_terms: tuple[str, ...] = DEFAULT_ERROR_TERMS

    @classmethod
    def load(cls) -> VisionConfig:
        """Carrega a configuração a partir do ambiente."""
        terms = tuple(
            t.strip().lower()
            for t in os.getenv("ARIS_VISION_ERROR_TERMS", "").split(",")
            if t.strip()
        ) or DEFAULT_ERROR_TERMS
        return cls(
            enabled=_env_bool("ARIS_VISION_ENABLED", True),
            screen_enabled=_env_bool("ARIS_SCREEN_VISION_ENABLED", True),
            ocr_enabled=_env_bool("ARIS_OCR_ENABLED", True),
            vlm_enabled=_env_bool("ARIS_VLM_ENABLED", True),
            camera_enabled=_env_bool("ARIS_VISION_CAMERA_ENABLED", False),
            vlm_provider=os.getenv("ARIS_VLM_PROVIDER", "ollama").strip().lower() or "ollama",
            vlm_model=os.getenv("ARIS_VLM_MODEL", "").strip(),
            ollama_base_url=os.getenv("ARIS_OLLAMA_BASE_URL", "http://localhost:11434"),
            vision_timeout=_env_float("ARIS_VISION_TIMEOUT", 30.0),
            max_image_size=_env_int("ARIS_VISION_MAX_IMAGE_SIZE", 1024),
            save_images=_env_bool("ARIS_VISION_SAVE_IMAGES", False),
            save_dir=os.getenv("ARIS_VISION_SAVE_DIR", "").strip(),
            error_terms=terms,
        )

    def update_env(self, **overrides: object) -> VisionConfig:
        """Nova configuração com os campos fornecidos sobrescritos."""
        data = {
            f.name: getattr(self, f.name)
            for f in self.__dataclass_fields__.values()
        }
        data.update(overrides)
        return self.__class__(**data)

    def as_env_doc(self) -> str:
        """Documenta as variáveis de ambiente (para README/.env.example)."""
        return "\n".join(
            f"ARIS_VISION_ENABLED={self.enabled}",
            f"ARIS_SCREEN_VISION_ENABLED={self.screen_enabled}",
            f"ARIS_OCR_ENABLED={self.ocr_enabled}",
            f"ARIS_VLM_ENABLED={self.vlm_enabled}",
            f"ARIS_VISION_CAMERA_ENABLED={self.camera_enabled}",
            f"ARIS_VLM_PROVIDER={self.vlm_provider}",
            f"ARIS_VLM_MODEL={self.vlm_model}",
            f"ARIS_OLLAMA_BASE_URL={self.ollama_base_url}",
            f"ARIS_VISION_TIMEOUT={self.vision_timeout}",
            f"ARIS_VISION_MAX_IMAGE_SIZE={self.max_image_size}",
            f"ARIS_VISION_SAVE_IMAGES={self.save_images}",
            f"ARIS_VISION_SAVE_DIR={self.save_dir}",
        )
