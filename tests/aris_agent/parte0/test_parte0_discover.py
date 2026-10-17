"""Testes da auto-descoberta de ferramentas (Parte 0)."""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path

from aris_agent.tools import ToolRegistry, discover


def _cria_pacote_falso(tmp_path: Path) -> tuple[str, Path]:
    name = f"fake_tools_{uuid.uuid4().hex[:8]}"
    pkg = tmp_path / name
    (pkg / "good").mkdir(parents=True)
    (pkg / "bad").mkdir()
    (pkg / "sem_register").mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "soltura.py").write_text("X = 1\n", encoding="utf-8")
    (pkg / "sem_register" / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    (pkg / "good" / "__init__.py").write_text(
        "def register(registry):\n"
        "    from aris_agent.fakes import EchoTool\n"
        "    registry.register(EchoTool())\n",
        encoding="utf-8",
    )
    (pkg / "bad" / "__init__.py").write_text(
        "raise ImportError('dependência ausente')\n", encoding="utf-8"
    )
    return name, pkg


def _limpa(name: str, tmp_path: Path) -> None:
    if str(tmp_path) in sys.path:
        sys.path.remove(str(tmp_path))
    for mod in (name, f"{name}.good", f"{name}.bad", f"{name}.sem_register"):
        sys.modules.pop(mod, None)


def test_discover_pula_subpacote_quebrado(tmp_path, caplog) -> None:
    name, _ = _cria_pacote_falso(tmp_path)
    sys.path.insert(0, str(tmp_path))
    try:
        module = importlib.import_module(name)
        registry = ToolRegistry()
        processados = discover(registry, package=module)
    finally:
        _limpa(name, tmp_path)

    assert processados == ["good"]
    assert "echo" in registry
    avisos = [r.getMessage() for r in caplog.records]
    assert any("bad" in m and "falhou ao importar" in m for m in avisos), avisos


def test_discover_ignora_modulo_sem_register(tmp_path, caplog) -> None:
    name, _ = _cria_pacote_falso(tmp_path)
    sys.path.insert(0, str(tmp_path))
    try:
        module = importlib.import_module(name)
        registry = ToolRegistry()
        processados = discover(registry, package=module)
    finally:
        _limpa(name, tmp_path)

    assert "sem_register" not in processados
    # sem aviso de WARNING: só debug
    assert not [r for r in caplog.records if r.levelname == "WARNING" and "sem_register" in r.getMessage()]


def test_discover_no_pacote_real_nao_quebra() -> None:
    registry = ToolRegistry()
    processados = discover(registry)
    assert isinstance(processados, list)
    assert "registry" not in processados


def test_import_smoke() -> None:
    import aris_agent
    import aris_agent.tools

    assert aris_agent.__version__
