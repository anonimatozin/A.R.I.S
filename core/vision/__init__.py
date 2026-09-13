"""Vision Engine do A.R.I.S.

Camada de visão computacional que transforma imagens em informação
estruturada:

    tela/câmera → captura → OCR + VLM → VisionResult
                                        → Event Bus → Atenção → Contexto/Memória

Princípios (conforme especificação):
    - funciona sem câmera (ScreenSource implementada; CameraSource preparada);
    - OCR (Tesseract) e VLM (Ollama/Gemini) são independentes e opcionais;
    - fallback em níveis — nenhum componente indisponível causa crash;
    - a visão é sob demanda: nunca captura/envia a tela continuamente;
    - capturas são temporárias por padrão (sem salvar imagem);
    - visão apenas observa: nenhuma ação é executada a partir do VLM.
"""

from core.vision.config import VisionConfig
from core.vision.result import OcrResult, OcrWord, VisionAnalysis, VisionResult
from core.vision.vision_engine import VisionEngine

__all__ = [
    "VisionConfig",
    "OcrResult",
    "OcrWord",
    "VisionAnalysis",
    "VisionResult",
    "VisionEngine",
]
