"""Parte 9 — modo live contra o LLM real (pulado por padrão).

Ative com ``ARIS_TEST_LIVE=1`` ou ``pytest -m live``. Exige a seção ``llm``
configurada no ``aris_agent.json`` (provedores + chains).
"""

from __future__ import annotations

import pytest

from aris_agent.evals.runner import run_live
from aris_agent.evals.scenarios import filter_scenarios, load_scenarios

pytestmark = pytest.mark.live


def test_live_uma_tarefa_de_conta() -> None:
    cenarios = filter_scenarios(load_scenarios(), categoria="conta")[:1]
    assert cenarios
    try:
        resultados = run_live(cenarios, max_tasks=1)
    except RuntimeError as exc:
        pytest.skip(f"sem LLM configurado: {exc}")
    assert len(resultados) == 1
    item = resultados[0]
    # no modo live o LLM é real: o relatório é honesto, não exigimos 100%
    assert item.stopped_reason in {"done", "max_steps", "budget", "error"}
    assert item.falhas is not None


def test_live_sem_provedores_levanta_erro_claro(monkeypatch) -> None:
    import tempfile
    from pathlib import Path

    from aris_agent.config import AgentConfig

    cfg = AgentConfig(
        workspace_dir=Path(tempfile.mkdtemp()),
        data_dir=Path(tempfile.mkdtemp()),
    )
    # garante a ausência de provedores independente do aris_agent.json da máquina
    monkeypatch.setattr(type(cfg), "section", lambda self, name: {})
    cenarios = filter_scenarios(load_scenarios(), categoria="conta")[:1]
    with pytest.raises(RuntimeError, match="sem provedores"):
        run_live(cenarios, config=cfg, max_tasks=1)
