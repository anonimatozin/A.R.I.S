"""Ponte da ARIS antiga com o agente novo (Parte 8).

Uso típico (feito em ``core/aris.py`` e ``edge/edge_chat.py``)::

    from aris_agent.bridge import build_bridge

    ponte = build_bridge(falar=..., ouvir=...)
    resposta = ponte.processar(texto)   # None => continua o fluxo antigo

Interruptor ``ARIS_AGENT_ENABLED`` (padrão **desligado**); qualquer falha de
import/construção devolve ``None`` com aviso — a ARIS antiga nunca cai.
"""

from __future__ import annotations

from .eventos import FaladorDeEventos
from .factory import PacoteAgente, build_agent
from .migracao import caminho_memoria_antiga, importar_memoria_antiga
from .ponte import Ponte, build_bridge
from .rota import Roteador, normalizar
from .voz import ConfirmanteDeVoz, entrada_com_tempo, interpretar_resposta

__all__ = [
    "ConfirmanteDeVoz",
    "FaladorDeEventos",
    "PacoteAgente",
    "Ponte",
    "Roteador",
    "build_agent",
    "build_bridge",
    "caminho_memoria_antiga",
    "entrada_com_tempo",
    "importar_memoria_antiga",
    "interpretar_resposta",
    "normalizar",
]
