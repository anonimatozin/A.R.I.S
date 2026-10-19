"""Detectores de wake word dedicados — STT só DEPOIS de acordar.

O sensor de voz contínua rodava o STT em todo trecho de fala e só depois
procurava a wake word no texto: CPU alta o tempo todo, tudo falado era
transcrito (privacidade) e latência. Estes motores respondem à pergunta
"o áudio deste frame acordou a ARIS?" com uma interface pequena:

    class WakeEngine(Protocol):
        def process(self, frame_pcm16_16k: bytes) -> float: ...  # 0..1
        def reset(self) -> None: ...

Implementações:

- TranscriptWakeEngine — o comportamento antigo (VAD -> STT ->
  matches_wake_word) como fallback: não quebrar quem já usa e continua
  sendo o modo padrão do sensor.
- OpenWakeWordEngine — openWakeWord (offline, ONNX/TFLite) olhando o áudio
  direto, sem transcrever nada antes de acordar. Dependência opcional
  (requirements-optional.txt); o modelo pré-treinado é em inglês, para
  treinar o da Áris ver docs/WAKE_WORD.md.

API do openWakeWord confirmada na documentação oficial (v0.6.0):
`from openwakeword.model import Model`; `Model(wakeword_models=[caminho])`
aceita caminho de .onnx/.tflite ou nome pré-treinado; `predict(frame)`
recebe PCM 16 kHz (frames múltiplos de 80 ms recomendados) e no v0.6
devolve dict {nome_modelo: score} (versões antigas: array).

Seleção por variável de ambiente (o sensor consulta antes de criar):

    ARIS_WAKE_ENGINE=openwakeword|transcript   padrão: transcript
    ARIS_WAKE_MODEL=<caminho .onnx/.tflite>    modelo próprio (Áris)
    ARIS_WAKE_THRESHOLD=0.5                    limiar 0..1

Sem modelo "Áris" treinado, use um pré-treinado do openWakeWord só para
testar o pipeline (ver docs/WAKE_WORD.md). Garantias: import tardio,
nenhuma exceção sobe do processamento de frame (score 0.0 + log) e
engine inválido cai no transcript com um aviso.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: Wake words padrão (o sensor injeta as suas).
WAKE_WORDS_PADRAO = ("aris", "arís", "ariz", "arizs")


def escolher_engine() -> str:
    """'openwakeword' ou 'transcript' (padrão). Valor inválido: aviso + transcript."""
    nome = os.getenv("ARIS_WAKE_ENGINE", "transcript").strip().lower()
    if nome == "openwakeword":
        return "openwakeword"
    if nome != "transcript":
        logger.warning(
            "ARIS_WAKE_ENGINE=%r desconhecido — usando 'transcript' "
            "(valores válidos: openwakeword, transcript)", nome,
        )
        return "transcript"
    return "transcript"


def limiar_padrao() -> float:
    """Limiar do motor dedicado (ARIS_WAKE_THRESHOLD, padrão 0.5)."""
    bruto = os.getenv("ARIS_WAKE_THRESHOLD", "").strip()
    try:
        valor = float(bruto) if bruto else 0.5
    except ValueError:
        logger.warning("ARIS_WAKE_THRESHOLD=%r inválido — usando 0.5", bruto)
        return 0.5
    return min(max(valor, 0.0), 1.0)


@runtime_checkable
class WakeEngine(Protocol):
    """Interface dos motores de wake word (frame PCM16 16 kHz -> score 0..1)."""

    def process(self, frame_pcm16_16k: bytes) -> float:
        """Score 0..1 para este frame (>= 1.0 = acordou). Nunca levanta."""

    def reset(self) -> None:
        """Descarta contexto parcial (nova utterância/janela)."""


class TranscriptWakeEngine:
    """Fallback: o comportamento antigo por trás da interface WakeEngine.

    Acumula fala (VAD injetado ou "tudo é fala"), transcreve ao terminar a
    utterância e devolve 1.0 se `matches_wake_word` achar a wake word.
    É o mesmo custo/privacidade do sensor antigo — por isso continua sendo
    o PADRÃO, e não uma melhoria.

    Args:
        transcrever: função de STT `(pcm_bytes) -> texto | None` (a do sensor).
        is_speech: VAD injetado `(frame) -> bool` (None = tudo fala).
        wake_words: palavras que acordam a ARIS.
        sample_rate/frame_ms: geometria dos frames (para o limite de duração).
        silence_limit_frames: frames de silêncio que fecham a utterância.
        max_seconds: duração máxima acumulada antes de forçar o STT.
    """

    def __init__(
        self,
        transcrever: Callable[[bytes], str | None],
        is_speech: Callable[[bytes], bool] | None = None,
        wake_words: tuple = WAKE_WORDS_PADRAO,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        silence_limit_frames: int = 40,
        max_seconds: float = 30.0,
    ) -> None:
        from core.perception.continuous_voice_sensor import matches_wake_word

        self._transcrever = transcrever
        self._is_speech = is_speech
        self._matches = matches_wake_word
        self._wake_words = tuple(wake_words)
        self._silence_limit = max(1, silence_limit_frames)
        self._max_frames = max(1, int(max_seconds * 1000 / max(1, frame_ms)))
        self._buffer: list[bytes] = []
        self._silence = 0

    def process(self, frame_pcm16_16k: bytes) -> float:
        try:
            falando = (
                self._is_speech(frame_pcm16_16k)
                if self._is_speech is not None else True
            )
            if falando:
                self._buffer.append(frame_pcm16_16k)
                self._silence = 0
                if len(self._buffer) >= self._max_frames:
                    return self._fechar()
                return 0.0
            if not self._buffer:
                return 0.0
            self._buffer.append(frame_pcm16_16k)  # silêncio final p/ o STT
            self._silence += 1
            if self._silence >= self._silence_limit:
                return self._fechar()
            return 0.0
        except Exception:  # pragma: no cover - defesa: frame nunca derruba o loop
            logger.debug("TranscriptWakeEngine: frame ignorado", exc_info=True)
            return 0.0

    def _fechar(self) -> float:
        frames, self._buffer, self._silence = self._buffer, [], 0
        if not frames:
            return 0.0
        texto = self._transcrever(b"".join(frames)) or ""
        if texto and self._matches(texto, self._wake_words):
            return 1.0
        return 0.0

    def reset(self) -> None:
        self._buffer = []
        self._silence = 0


class OpenWakeWordEngine:
    """Motor dedicado openWakeWord (offline): nada é transcrito antes de acordar.

    Import tardio: sem a dependência opcional instalada o construtor levanta
    ImportError com instrução clara (o chamador costuma cai no transcript
    com um aviso — ver `criar_engine`).
    """

    def __init__(
        self,
        model_path: str = "",
        wake_word_name: str = "aris",
        limiar: float = 0.5,
    ) -> None:
        try:
            from openwakeword.model import Model
        except ImportError as exc:
            raise ImportError(
                "openWakeWord não instalado. Instale com: "
                "pip install --no-deps openwakeword && pip install onnxruntime "
                "(Linux+Python 3.12: tflite-runtime não tem wheel — ver "
                "requirements-optional.txt e docs/WAKE_WORD.md)."
            ) from exc

        self._limiar = float(limiar)
        try:
            if model_path:
                # Modelo próprio treinado para a Áris (.onnx/.tflite).
                self._modelo = Model(wakeword_models=[model_path])
            else:
                # Modelo pré-treinado do openWakeWord (inglês) — só p/ testar
                # o pipeline end-to-end; o da Áris precisa ser treinado.
                self._modelo = Model(wake_words=[wake_word_name])
        except Exception as exc:
            # Pacote meio-instalado (ex.: `--no-deps` sem o scipy): o import
            # do Model acima funciona, mas a construção deles explode com
            # erro interno (AttributeError etc.). Vira o MESMO erro
            # instrutivo — o chamador (criar_engine) cai no transcript com
            # aviso em vez de estourar erro cru de terceiros.
            raise ImportError(
                "openWakeWord instalado porém inutilizável "
                f"({type(exc).__name__}: {exc}) — reinstale conforme "
                "requirements-optional.txt e docs/WAKE_WORD.md."
            ) from exc

    def process(self, frame_pcm16_16k: bytes) -> float:
        try:
            pred = self._modelo.predict(frame_pcm16_16k)
        except Exception:  # pragma: no cover - defesa: frame nunca derruba o loop
            logger.debug("OpenWakeWordEngine: frame ignorado", exc_info=True)
            return 0.0
        return _score_max(pred)

    def reset(self) -> None:
        try:
            if hasattr(self._modelo, "reset"):
                self._modelo.reset()
        except Exception:  # pragma: no cover - defesa
            logger.debug("OpenWakeWordEngine: reset ignorado", exc_info=True)


def _score_max(pred) -> float:
    """Maior score da predição (dict no v0.6; array/lista em versões antigas)."""
    try:
        if isinstance(pred, dict):
            valores = [float(v) for v in pred.values()]
        else:
            valores = [float(v) for v in pred]
        return max(valores) if valores else 0.0
    except Exception:  # pragma: no cover - defesa
        return 0.0


def criar_engine(
    transcrever: Callable[[bytes], str | None] | None = None,
    is_speech: Callable[[bytes], bool] | None = None,
    wake_words: tuple = WAKE_WORDS_PADRAO,
    sample_rate: int = 16000,
    frame_ms: int = 30,
) -> WakeEngine | None:
    """Cria o motor escolhido por ARIS_WAKE_ENGINE. Nunca levanta exceção.

    - openwakeword: OpenWakeWordEngine; se a dependência/modelo faltar,
      avisa UMA vez e devolve o TranscriptWakeEngine equivalente.
    - transcript (padrão): TranscriptWakeEngine com o STT/VAD injetados;
      sem `transcrever` injetado devolve None (o chamador usa o fluxo nativo).
    """
    nome = escolher_engine()
    if nome == "openwakeword":
        try:
            return OpenWakeWordEngine(
                model_path=os.getenv("ARIS_WAKE_MODEL", "").strip(),
                limiar=limiar_padrao(),
            )
        except Exception as exc:
            logger.warning(
                "openWakeWord indisponível (%s) — wake word cai no modo transcript", exc,
            )
    if transcrever is None:
        return None
    return TranscriptWakeEngine(
        transcrever=transcrever,
        is_speech=is_speech,
        wake_words=wake_words,
        sample_rate=sample_rate,
        frame_ms=frame_ms,
    )
