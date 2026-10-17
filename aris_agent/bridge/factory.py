"""Fábrica da ponte: monta o agente completo (Parte 8).

Qualquer falha aqui vira ``None`` + aviso em log — nunca exceção: a ARIS
antiga não pode cair porque o agente novo não carregou.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - só para type checkers
    from ..config import AgentConfig

log = logging.getLogger("aris.agent.bridge.factory")

PERFIS_VALIDOS = ("desktop", "edge")


@dataclass
class PacoteAgente:
    """Peças montadas pela fábrica para a ponte operar."""

    agente: Any  # ArisAgent
    executor: Any  # SafeExecutor
    kill_switch: Any  # KillSwitch (executor.kill_switch)
    memoria: Any  # SqliteMemory
    skills: Any  # SkillLibrary
    registry: Any  # ToolRegistry
    perfil: str = "desktop"


def build_agent(cfg: AgentConfig, *, perfil: str = "desktop", llm: Any = None) -> PacoteAgente | None:
    """Monta o ``ArisAgent`` para ``cfg``; devolve ``None`` + log se faltar algo.

    - ``perfil="desktop"``: todas as ferramentas descobertas (Partes 2/3/4/6).
    - ``perfil="edge"``: só ``web_*`` + memória (celular: nada de PC).
    - ``llm``: opcional (testes injetam ``FakeLLM``); sem ele, usa a seção
      ``llm`` do ``aris_agent.json``.
    """
    try:
        from ..core.agent import ArisAgent
        from ..llm.router import LLMRouter
        from ..llm.settings import parse_settings
        from ..memory.sqlite import SqliteMemory
        from ..safety.executor import SafeExecutor
        from ..safety.settings import SafetySettings
        from ..skills.library import SkillLibrary
        from ..tools import discover
        from ..tools.memory_tools import register as registrar_memoria
        from ..tools.memory_tools import set_memory
        from ..tools.registry import ToolRegistry
        from ..tools.skill_tools import set_library
        from ..tools.web import register as registrar_web
    except Exception as exc:  # noqa: BLE001 - qualquer import quebrado desliga o agente
        log.warning("agente desativado: importação falhou: %s", exc)
        return None

    if perfil not in PERFIS_VALIDOS:
        log.warning("agente desativado: perfil desconhecido %r (use %s)", perfil, PERFIS_VALIDOS)
        return None

    try:
        registry = ToolRegistry()
        if perfil == "edge":
            # O register() do pacote web inclui browser_* (ferramenta do PC,
            # com navegador local — não existe no celular). Monta num registry
            # temporário e mantém só web_* + memory_*.
            temporario = ToolRegistry()
            registrar_web(temporario)
            registrar_memoria(temporario)
            for spec in temporario.specs():
                if spec.name.startswith(("web_", "memory_")):
                    registry.register(temporario.get(spec.name))
        else:
            discover(registry)

        if llm is None:
            secao = cfg.section("llm")
            if not secao.get("providers"):
                log.warning(
                    "agente desativado: seção 'llm' sem providers no aris_agent.json "
                    "(copie aris_agent.example.json e aponte api_key_env para GROQ_API_KEY)"
                )
                return None
            llm = LLMRouter(parse_settings(secao), data_dir=cfg.data_dir)
        memoria = SqliteMemory(cfg.data_dir / "aris_agent_memory.db")
        set_memory(memoria)
        biblioteca = SkillLibrary.from_config(cfg)
        set_library(biblioteca)
        executor = SafeExecutor(
            registry,
            cfg,
            settings=SafetySettings.from_section(cfg.section("safety"), cfg),
        )
        agente = ArisAgent(llm, executor, registry, memoria, biblioteca, cfg)
        return PacoteAgente(
            agente=agente,
            executor=executor,
            kill_switch=executor.kill_switch,
            memoria=memoria,
            skills=biblioteca,
            registry=registry,
            perfil=perfil,
        )
    except Exception as exc:  # noqa: BLE001 - vira aviso, nunca derruba a ARIS
        log.warning("agente desativado: falha ao montar: %s", exc)
        return None
