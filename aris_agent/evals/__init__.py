"""Avaliação da ARIS-agente: cenários, executores, traces e intenções.

* :mod:`~aris_agent.evals.scenarios` — carga/validação dos cenários JSONL.
* :mod:`~aris_agent.evals.runner` — ``run_scripted`` (CI, sem rede) e
  ``run_live`` (LLM real), relatório por categoria em JSON/Markdown.
* :mod:`~aris_agent.evals.trace_view` — HTML offline da linha do tempo.
* :mod:`~aris_agent.evals.intents` — dataset rotulado + avaliação do
  classificador de intenções (usado pela Parte 8).

Como rodar: ``docs/agent/AVALIACAO.md``.
"""

from __future__ import annotations

__all__ = ["scenarios", "runner", "trace_view", "intents", "run"]
