"""Testes de pc_run_command e pc_python_run (comuns: cmd/python do próprio sistema)."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.types import ToolContext
from aris_agent.tools import ToolRegistry
from aris_agent.tools import pc as pacote_pc


def make_ctx(tmp_path: Path) -> ToolContext:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data")
    return ToolContext(session_id="s", workdir=tmp_path, config=cfg, cancel=threading.Event())


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    pacote_pc.register(registry)
    return registry


def run(registry: ToolRegistry, name: str, args: dict, ctx: ToolContext):
    return registry.get(name).run(args, ctx)


@pytest.mark.windows  # sintaxe cmd.exe (%CD%, 1>&2): só existe no Windows
def test_run_command_echo_cmd(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_run_command", {"command": "echo ola-mundo", "shell": "cmd"}, ctx)
    assert result.ok, result.error
    assert result.data["returncode"] == 0
    assert "ola-mundo" in result.content


@pytest.mark.windows
def test_run_command_codigo_de_saida_diferente(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_run_command", {"command": "exit 7", "shell": "cmd"}, ctx)
    assert result.ok, "ferramenta deve ok=True mesmo com exit code != 0"
    assert result.data["returncode"] == 7
    assert "código de saída: 7" in result.content


@pytest.mark.windows
def test_run_command_usa_cwd(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    (tmp_path / "subpasta").mkdir()
    result = run(
        reg,
        "pc_run_command",
        {"command": "echo %CD%", "shell": "cmd", "cwd": "subpasta"},
        ctx,
    )
    assert result.ok, result.error
    assert "subpasta" in result.content.lower()


def test_run_command_cwd_fora_das_raizes(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(
        reg, "pc_run_command", {"command": "echo x", "shell": "cmd", "cwd": str(tmp_path.parent)},
        ctx,
    )
    assert not result.ok
    assert "fora das raízes" in (result.error or "")


@pytest.mark.windows
def test_run_command_captura_stderr(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(
        reg, "pc_run_command", {"command": "echo sai-pelo-stderr 1>&2", "shell": "cmd"}, ctx
    )
    assert result.ok
    assert "sai-pelo-stderr" in (result.data["stderr"] or "") or "sai-pelo-stderr" in result.content


def test_run_command_comando_vazio(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    assert not run(reg, "pc_run_command", {"command": "   "}, ctx).ok
    assert not run(reg, "pc_run_command", {}, ctx).ok


def test_run_command_shell_desconhecido(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    # "xilsh" não existe em nenhuma plataforma (bash seria válido no Linux)
    result = run(reg, "pc_run_command", {"command": "ls", "shell": "xilsh"}, ctx)
    assert not result.ok
    assert "shell" in (result.error or "")


@pytest.mark.windows
def test_run_command_timeout_mata_arvore_de_processos(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    marker = f"aris_marker_{uuid.uuid4().hex[:8]}"
    command = f'python -c "import time; time.sleep(60) #{marker}"'
    inicio = time.monotonic()
    result = run(
        reg, "pc_run_command", {"command": command, "shell": "cmd", "timeout_s": 1}, ctx
    )
    decorrido = time.monotonic() - inicio
    assert not result.ok
    assert "timeout" in (result.error or "")
    assert decorrido < 20, f"timeout demorou {decorrido:.1f}s"
    assert _processo_vivo(marker) is False, "o filho python deveria ter morrido com a árvore"


@pytest.mark.windows
def test_run_command_cancelado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    ctx.cancel.set()
    result = run(reg, "pc_run_command", {"command": "echo oi", "shell": "cmd"}, ctx)
    assert not result.ok
    assert "cancelado" in (result.error or "")


def _processo_vivo(marker: str) -> bool:
    """Procura processos cujo cmdline contenha o marcador (com margem de tempo)."""
    import psutil

    prazo = time.monotonic() + 5
    while time.monotonic() < prazo:
        achou = False
        for processo in psutil.process_iter(["cmdline"]):
            try:
                cmdline = " ".join(processo.info.get("cmdline") or [])
            except Exception:  # noqa: BLE001
                continue
            if marker in cmdline:
                achou = True
                break
        if not achou:
            return False
        time.sleep(0.2)
    return True


def test_python_run_basico(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_python_run", {"code": "print(2 ** 10)"}, ctx)
    assert result.ok, result.error
    assert result.data["returncode"] == 0
    assert "1024" in result.content


    antes = _dirs_python_tmp()
    run(reg, "pc_python_run", {"code": "print('x')"}, ctx)
    assert _dirs_python_tmp() <= antes, "a pasta temporária deveria ser removida"


def test_python_run_ignora_variaveis_sensiveis(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINHA_API_KEY", "segredo-nao-pode-vazar")
    monkeypatch.setenv("OUTRO_TOKEN", "token-nao-pode-vazar")
    monkeypatch.setenv("ALGO_SECRET", "segredo2-nao-pode-vazar")
    monkeypatch.setenv("VAR_NORMAL", "valor-ok")
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    code = (
        "import os\n"
        "print(os.environ.get('MINHA_API_KEY'))\n"
        "print(os.environ.get('OUTRO_TOKEN'))\n"
        "print(os.environ.get('ALGO_SECRET'))\n"
        "print(os.environ.get('VAR_NORMAL'))\n"
    )
    result = run(reg, "pc_python_run", {"code": code}, ctx)
    assert result.ok, result.error
    stdout = result.data["stdout"]
    assert "segredo-nao-pode-vazar" not in stdout
    assert "token-nao-pode-vazar" not in stdout
    assert "segredo2-nao-pode-vazar" not in stdout
    assert stdout.count("None") == 3
    assert "valor-ok" in stdout


def test_python_run_erro_de_sintaxe(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_python_run", {"code": "def quebrado(: pass"}, ctx)
    assert result.ok, "subprocesso rodou; o erro é do código"
    assert result.data["returncode"] != 0
    assert "SyntaxError" in result.content


def test_python_run_excecao_nao_larga_excecao_vazar(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_python_run", {"code": "raise ValueError('boom')"}, ctx)
    assert result.ok
    assert "ValueError: boom" in result.content


def test_python_run_timeout(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    antes = _dirs_python_tmp()
    inicio = time.monotonic()
    result = run(reg, "pc_python_run", {"code": "import time; time.sleep(60)", "timeout_s": 1}, ctx)
    decorrido = time.monotonic() - inicio
    assert not result.ok
    assert "timeout" in (result.error or "")
    assert decorrido < 20, f"timeout demorou {decorrido:.1f}s"
    assert _dirs_python_tmp() <= antes, "a pasta temporária deveria ser removida no timeout"


def test_python_run_cancelado(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    ctx.cancel.set()
    result = run(reg, "pc_python_run", {"code": "print(1)"}, ctx)
    assert not result.ok
    assert "cancelado" in (result.error or "")


def test_python_run_code_vazio(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    assert not run(reg, "pc_python_run", {"code": ""}, ctx).ok
    assert not run(reg, "pc_python_run", {}, ctx).ok


def test_python_run_aceita_unicode(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_python_run", {"code": "print('ação çãé')"}, ctx)
    assert result.ok, result.error
    assert "ação çãé" in result.content


def _dirs_python_tmp() -> set[str]:
    base = Path(tempfile.gettempdir())
    return {path.name for path in base.glob("aris_py_*")}


def test_python_executavel_do_sistema(tmp_path) -> None:
    """Garante que usamos o mesmo interpretador do ambiente."""
    ctx = make_ctx(tmp_path)
    reg = make_registry()
    result = run(reg, "pc_python_run", {"code": "import sys; print(sys.executable)"}, ctx)
    assert result.ok
    assert Path(result.data["stdout"].strip()).resolve() == Path(sys.executable).resolve()
