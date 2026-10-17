"""Confirmação por voz/teclado da ponte (Parte 8).

``ConfirmanteDeVoz`` fala o resumo da ação e espera "sim/não" por voz ou
teclado. **Timeout = negar.** Ações ``hard_confirm`` (destrutivas/em lote)
só passam com afirmação explícita no começo da resposta.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import unicodedata

log = logging.getLogger("aris.agent.bridge.voz")

# Resposta com qualquer uma destas palavras nega (negação vence sempre).
NEGATIVAS = frozenset({"nao", "n", "no", "cancela", "cancelar", "para", "pare", "deixa", "nunca"})
# hard_confirm: só afirmação explícita no começo da frase.
AFIRMACOES_EXPLICITAS = frozenset({"sim", "confirma", "confirmo", "confirme"})
# resposta solta (soft): basta a palavra aparecer.
AFIRMACOES_SOLTAS = frozenset({"sim", "pode", "confirma", "confirmo", "confirme", "isso", "vai", "bora"})


def _limpar(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços colapsados."""
    base = (
        unicodedata.normalize("NFKD", str(texto))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return " ".join(base.lower().split())


def interpretar_resposta(resposta: str | None, *, hard: bool = False) -> bool:
    """Converte fala/teclado em decisão. ``None``/vazio/timeout → ``False``."""
    if resposta is None:
        return False
    base = _limpar(resposta).strip(" .!?")
    if not base:
        return False
    # cada palavra sai sem pontuação colada ("sim," conta como "sim")
    palavras = {p.strip(",;:.!?") for p in base.split()}
    palavras.discard("")
    if palavras & NEGATIVAS:
        return False  # qualquer dúvida nega; negação sempre vence
    if hard:
        primeiro = next(iter(base.split())).strip(",;:.!?")
        return primeiro in AFIRMACOES_EXPLICITAS
    return bool(palavras & AFIRMACOES_SOLTAS)


class ConfirmanteDeVoz:
    """``ConfirmFn``: fala o ``args_preview`` e ouve a resposta do chefe."""

    def __init__(
        self,
        falar,
        ouvir,
        *,
        timeout_s: float = 15.0,
        fala_max_s: float = 4.0,
        logger=None,
    ) -> None:
        self._falar = falar
        self._ouvir = ouvir
        self.timeout_s = max(1.0, float(timeout_s))
        self.fala_max_s = max(0.1, float(fala_max_s))
        self._log = logger or log

    def __call__(self, pedido) -> bool:
        """Responde ``True`` só com confirmação clara; timeout/dúvida nega."""
        preview = str(getattr(pedido, "args_preview", "") or pedido.tool_name).strip()
        hard = bool(getattr(pedido, "hard_confirm", False))
        if hard:
            pergunta = (
                f"Chefe, {preview}. Atenção: é ação destrutiva. "
                "Responda sim para confirmar."
            )
        else:
            pergunta = f"Chefe, {preview}. Confirma?"

        # A fala roda com TETO: um TTS lento/quebrado (retries) não pode
        # comer o orçamento inteiro da confirmação — a ouvida começa com o
        # tempo que sobrar (orçamento esgotado falando = nega).
        inicio = time.monotonic()
        fio = threading.Thread(
            target=self._falar_protegido,
            args=(pergunta,),
            daemon=True,
            name="aris-confirm-fala",
        )
        fio.start()
        fio.join(min(self.fala_max_s, self.timeout_s * 0.4))
        restante = self.timeout_s - (time.monotonic() - inicio)
        if restante < 1.0:
            self._log.warning(
                "confirmação de %s: orçamento esgotado na fala (TTS lento?) — negando",
                pedido.tool_name,
            )
            return False
        try:
            resposta = self._ouvir(restante)
        except Exception as exc:  # noqa: BLE001
            self._log.warning("não consegui ouvir a confirmação: %s", exc)
            resposta = None
        decidido = interpretar_resposta(resposta, hard=hard)
        self._log.info(
            "confirmação de %s: %s",
            pedido.tool_name,
            "sim" if decidido else "não/timeout",
        )
        return decidido

    def _falar_protegido(self, pergunta: str) -> None:
        """Fala isolada: erro do TTS não derruba a confirmação."""
        try:
            self._falar(pergunta, sync=True)
        except Exception as exc:  # noqa: BLE001
            self._log.warning("não consegui falar a confirmação: %s", exc)


# ---------------------------------------------------------------- teclado

_lock = threading.Lock()


def entrada_com_tempo(timeout_s: float, *, prompt: str = "") -> str | None:
    """Lê uma linha do teclado com timeout (``None`` ao estourar).

    ``input``/``select`` não têm timeout nativo (e no Windows ``select`` nem
    cobre o stdin): uma thread lê e o ``join`` espera. Leitura órfã que só
    terminar depois do timeout é descartada por token.
    """
    with _lock:
        entrada_com_tempo._token = getattr(entrada_com_tempo, "_token", 0) + 1
        meu_token = entrada_com_tempo._token
    guardado: dict[str, object] = {"valido": True, "resp": None}

    def _ler() -> None:
        try:
            linha: str | None = input(prompt)
        except Exception:  # noqa: BLE001 - EOF/Ctrl+C durante a espera
            linha = None
        if guardado.get("valido") and meu_token == getattr(entrada_com_tempo, "_token", None):
            guardado["resp"] = linha

    fio = threading.Thread(target=_ler, daemon=True, name="aris-confirm-teclado")
    fio.start()
    fio.join(max(1.0, float(timeout_s)))
    if fio.is_alive():
        guardado["valido"] = False  # estourou o tempo: descarta o que vier depois
        return None
    resp = guardado.get("resp")
    return resp if isinstance(resp, str) else None


def segundos_para_ouvinte(timeout_s: float) -> int:
    """Timeout em segundos inteiros para ``HybridVoice.listen(timeout=...)``."""
    return max(1, int(math.ceil(float(timeout_s))))
