"""Parte 8 — instância EDGE: agente desligado por padrão, falha é graciosa."""

from __future__ import annotations

import pytest

from edge.edge_chat import _AGENTE_EDGE, _agente_edge


@pytest.fixture(autouse=True)
def _zera_cache_da_ponte(monkeypatch) -> None:
    _AGENTE_EDGE["ponte"] = None
    _AGENTE_EDGE["tentou"] = False
    yield
    _AGENTE_EDGE["ponte"] = None
    _AGENTE_EDGE["tentou"] = False


def _isola_config(tmp_path, monkeypatch) -> None:
    """Impede de achar/gerar arquivos de configuração fora do teste."""
    monkeypatch.setattr("aris_agent.config._project_root", lambda: tmp_path)
    monkeypatch.setattr("aris_agent.config.DEFAULT_WORKSPACE", tmp_path / "ws")
    monkeypatch.setattr("aris_agent.config.DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setenv("ARIS_AGENT_DATA_DIR", str(tmp_path / "data"))


def test_desligado_nem_tenta_construir(monkeypatch, tmp_path) -> None:
    _isola_config(tmp_path, monkeypatch)
    monkeypatch.delenv("ARIS_AGENT_ENABLED", raising=False)
    monkeypatch.delenv("ARIS_AGENT_AGENT_ENABLED", raising=False)
    assert _agente_edge("oi, aris") is None
    assert _AGENTE_EDGE["tentou"] is False, "com o switch fora não pode nem montar"


def test_ligado_mas_sem_llm_cai_gracioso(monkeypatch, tmp_path) -> None:
    """Ligado sem providers: tenta, falha com aviso e segue o fluxo atual."""
    _isola_config(tmp_path, monkeypatch)
    monkeypatch.setenv("ARIS_AGENT_ENABLED", "true")
    monkeypatch.delenv("ARIS_AGENT_AGENT_ENABLED", raising=False)
    assert _agente_edge("apaga tudo") is None  # resposta None => fluxo do edge
    assert _AGENTE_EDGE["tentou"] is True
    assert _AGENTE_EDGE["ponte"] is None  # montagem falhou (sem providers)
    # segunda chamada não remonta (cache)
    assert _agente_edge("de novo") is None
