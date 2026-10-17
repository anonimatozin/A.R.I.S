"""Configuração compartilhada dos testes de `tests/aris_agent/`.

Registra os marcadores `live` e `windows` e os pula por padrão
(ative com `ARIS_TEST_LIVE=1` / `ARIS_TEST_WINDOWS=1` ou `-m live` / `-m windows`).
"""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: precisa de internet ou chave de API (pulado por padrão)"
    )
    config.addinivalue_line(
        "markers", "windows: precisa de APIs do Windows / interface (pulado por padrão)"
    )


def _enabled_by_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on", "sim"}


def _selected_by_markexpr(config: pytest.Config, marker: str) -> bool:
    expr = str(getattr(config.option, "markexpr", "") or "").lower()
    return marker in expr


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_live = _enabled_by_env("ARIS_TEST_LIVE") or _selected_by_markexpr(config, "live")
    run_windows = _enabled_by_env("ARIS_TEST_WINDOWS") or _selected_by_markexpr(
        config, "windows"
    )
    skip_live = pytest.mark.skip(
        reason="teste live (rede/chave): use ARIS_TEST_LIVE=1 ou -m live"
    )
    skip_windows = pytest.mark.skip(
        reason="teste de API do Windows: use ARIS_TEST_WINDOWS=1 ou -m windows"
    )
    for item in items:
        if not run_live and item.get_closest_marker("live"):
            item.add_marker(skip_live)
        if not run_windows and item.get_closest_marker("windows"):
            item.add_marker(skip_windows)
