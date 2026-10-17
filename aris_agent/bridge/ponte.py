"""Ponte: entrada única da ARIS antiga no agente novo (Parte 8).

``Ponte.processar`` devolve ``None`` quando o caminho antigo deve continuar
(conversa casual, switch desligado, kill já ativo) e a resposta falada quando
o agente tratou a tarefa. Qualquer exceção vira ``None`` ou frase de erro —
nunca propaga para o loop da ARIS.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from .eventos import FaladorDeEventos
from .factory import build_agent
from .migracao import importar_memoria_antiga
from .rota import Roteador
from .voz import ConfirmanteDeVoz

log = logging.getLogger("aris.agent.bridge.ponte")

SESSION_ID_PADRAO = "aris-local"
FALA_DE_PARADA = "Parei, chefe."
FALA_DE_ERRO = "Deu um problema aqui, chefe. Pode tentar de novo."
FALA_SEM_TEXTO = "Não consegui terminar, chefe."


class Ponte:
    """Conecta ``processar(texto)`` ao ``ArisAgent`` com kill/roteador/voz."""

    def __init__(
        self,
        *,
        pacote: Any,
        roteador: Roteador,
        confirmador: Callable[..., bool],
        falador: FaladorDeEventos,
        session_id: str = SESSION_ID_PADRAO,
    ) -> None:
        self._pacote = pacote
        self._agente = pacote.agente
        self._kill = pacote.kill_switch
        self._roteador = roteador
        self._confirmador = confirmador
        self._falador = falador
        self._session_id = session_id

    @property
    def kill_switch(self) -> Any:
        """``KillSwitch`` do executor (para atalhos externos/testes)."""
        return self._kill

    @property
    def pacote(self) -> Any:
        """Peças montadas (fábrica) — exposto para testes e diagnóstico."""
        return self._pacote

    def processar(self, texto: str, origin: Any = None) -> str | None:
        """Tenta tratar ``texto`` com o agente; ``None`` = caminho antigo."""
        if not str(texto or "").strip():
            return None

        # 1) parada de emergência vem antes de tudo
        if self._roteador.eh_de_parada(texto):
            self._kill.engage("parada por voz do usuário (ponte Parte 8)")
            return FALA_DE_PARADA

        # 2) depois de "para tudo", o agente fica quieto: deixa o caminho atual
        if self._kill.engaged:
            return None

        # 3) roteamento: conversa casual segue o fluxo antigo intacto
        if self._roteador.decidir(texto) == "conversa":
            return None

        # 4) tarefa → agente completo
        self._falador.reset()
        session = str(getattr(origin, "user_id", "") or "").strip() or self._session_id
        try:
            resultado = self._agente.run(
                texto,
                session_id=session,
                confirm=self._confirmador,
                events=self._falador,
            )
        except Exception as exc:  # noqa: BLE001 - nunca propaga para o loop
            log.error("tarefa do agente falhou: %s", exc, exc_info=True)
            return FALA_DE_ERRO

        if resultado.stopped_reason == "cancelled" or self._kill.engaged:
            return FALA_DE_PARADA
        resposta = str(resultado.text or "").strip()
        if not resposta:
            log.warning("agente terminou sem texto (%s)", resultado.stopped_reason)
            return FALA_SEM_TEXTO
        return resposta

    def parar(self) -> None:
        """Cancela execução em andamento (chamado no ``shutdown`` da ARIS)."""
        try:
            self._kill.engage("encerramento da ARIS")
        except Exception as exc:  # noqa: BLE001
            log.warning("não consegui engatar o kill switch: %s", exc)


def build_bridge(
    falar: Callable[..., None],
    ouvir: Callable[[float], str | None],
    *,
    cfg: Any = None,
    perfil: str | None = None,
    llm: Any = None,
) -> Ponte | None:
    """Monta a ponte se o interruptor estiver ligado; falha vira ``None``.

    Interruptor: ``ARIS_AGENT_ENABLED=true`` (ou ``"agent_enabled": true`` no
    ``aris_agent.json``) — **desligado por padrão**. Perfil:
    ``ARIS_AGENT_PERFIL`` (``desktop`` padrão, ou ``edge`` = só web + memória).
    """
    try:
        from ..config import load_config

        if cfg is None:
            cfg = load_config()
        if not cfg.agent_enabled:
            log.debug("agente desligado (ARIS_AGENT_ENABLED não ativo)")
            return None

        perfil_final = (
            perfil or os.environ.get("ARIS_AGENT_PERFIL") or "desktop"
        ).strip().lower()
        pacote = build_agent(cfg, perfil=perfil_final, llm=llm)
        if pacote is None:
            return None  # aviso já logado pela fábrica

        if pacote.perfil == "desktop":
            stats = importar_memoria_antiga(pacote.memoria)
            if stats:
                log.info("migração da memória antiga: %s", stats)

        ponte = Ponte(
            pacote=pacote,
            roteador=Roteador(),
            confirmador=ConfirmanteDeVoz(
                falar, ouvir, timeout_s=getattr(cfg, "confirm_timeout_s", 15.0)
            ),
            falador=FaladorDeEventos(falar),
        )
        log.info("ponte do agente pronta (perfil=%s, workspace=%s)",
                 pacote.perfil, cfg.workspace_dir)
        return ponte
    except Exception as exc:  # noqa: BLE001 - a ARIS nunca cai por causa da ponte
        log.warning("ponte do agente desativada: %s", exc)
        return None
