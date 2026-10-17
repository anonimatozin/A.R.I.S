"""Confirmação padrão para terminal (``ConfirmFn`` da Parte 5).

Regra: **timeout = negar**. A confirmação por voz (Parte 8) usa o mesmo tipo
``ConfirmFn``; ``make_cli_confirm`` aplica o timeout configurado.
"""

from __future__ import annotations

import builtins
import logging
import threading

from ..contract.types import ConfirmFn, ConfirmRequest

log = logging.getLogger("aris.agent.safety.confirm")

DEFAULT_TIMEOUT_S = 30.0
_YES = {"s", "sim", "y", "yes", "1", "ok", "confirmo", "pode"}


def format_request(request: ConfirmRequest) -> str:
    """Texto da pergunta mostrado no terminal (sem segredos; já vem redigido)."""
    nivel = "CONFIRMAÇÃO OBRIGATÓRIA" if request.hard_confirm else "confirmação"
    linhas = [
        f"[{nivel}] risco {request.risk.name}",
        f"ferramenta: {request.tool_name}",
        f"motivo: {request.reason}",
        "o que será feito:",
    ]
    for line in str(request.args_preview or "").splitlines() or ["(sem detalhes)"]:
        linhas.append(f"  {line}")
    linhas.append("Permitir? [s/N] ")
    return "\n".join(linhas)


def cli_confirm(
    request: ConfirmRequest,
    *,
    input_fn=None,
    timeout_s: float | None = None,
) -> bool:
    """Pergunta no terminal e devolve ``True`` só com resposta afirmativa.

    Sem resposta dentro do timeout (padrão 30 s ou ``timeout_s``), devolve
    ``False``: **negar é o padrão**. ``input_fn`` existe só para os testes.
    """
    timeout = DEFAULT_TIMEOUT_S if timeout_s is None else float(timeout_s)
    read = input_fn if input_fn is not None else builtins.input
    prompt = format_request(request)
    box: dict = {}

    def _read() -> None:
        try:
            box["answer"] = read(prompt)
        except (EOFError, KeyboardInterrupt, OSError):
            box["answer"] = ""
        except Exception as exc:  # noqa: BLE001 - entrada do usuário é imprevisível
            log.warning("falha ao ler confirmação: %s", exc)
            box["answer"] = ""

    reader = threading.Thread(target=_read, daemon=True, name="aris-confirm")
    reader.start()
    reader.join(timeout)
    if reader.is_alive():
        log.warning("confirmação expirou após %gs; negando por padrão", timeout)
        return False
    answer = str(box.get("answer", "")).strip().lower()
    return answer in _YES


def make_cli_confirm(config=None) -> ConfirmFn:
    """Cria um ``ConfirmFn`` de terminal com o timeout da configuração."""
    timeout = DEFAULT_TIMEOUT_S
    if config is not None:
        timeout = float(getattr(config, "confirm_timeout_s", DEFAULT_TIMEOUT_S) or DEFAULT_TIMEOUT_S)

    def _confirm(request: ConfirmRequest) -> bool:
        return cli_confirm(request, timeout_s=timeout)

    _confirm.__name__ = "cli_confirm"  # type: ignore[attr-defined]
    return _confirm
