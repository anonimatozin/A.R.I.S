"""Regressões de compatibilidade com Linux e de validação de entrada.

Cada teste aqui cobre um bug encontrado na revisão do projeto:
- a memória criava uma pasta literal "D:" no diretório atual fora do Windows;
- pc_system_status/pc_processes/... chamavam powershell/tasklist no Linux;
- pc_open_app exigia os.startfile (só Windows);
- safe_resolve não tratava "..\\..\\" como travessia no Linux;
- pc_logs interpolava o nome do log num comando PowerShell sem validar;
- pc_shutdown/restart montavam "-Force/f" (PowerShell inválido).
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

from core.memcore import paths as memcore_paths
from core.security.shell import PathTraversalError, safe_resolve
from core.tools import pc_control, pc_tools

linux_only = pytest.mark.skipif(os.name == "nt", reason="comportamento específico de Linux/macOS")


# ── memória: nada de pasta "D:" ───────────────────────────────────────────


@linux_only
def test_caminho_de_unidade_windows_e_reconhecido_como_estrangeiro() -> None:
    assert memcore_paths.is_foreign_windows_path("D:/ARIS_MEMORY")
    assert memcore_paths.is_foreign_windows_path(r"C:\Users\x\memory")
    assert not memcore_paths.is_foreign_windows_path("/home/x/memory")
    assert not memcore_paths.is_foreign_windows_path("data/memory")


@linux_only
def test_memoria_nao_cria_pasta_D_no_diretorio_atual(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ARIS_MEMORY_ROOT", raising=False)
    monkeypatch.setattr(memcore_paths, "_PROJECT_ROOT", tmp_path / "proj")

    root, available = memcore_paths.resolve_memory_root()

    assert available is True
    assert root == tmp_path / "proj" / "data" / "memory"
    assert not (tmp_path / "D:").exists()


@linux_only
def test_env_com_caminho_do_windows_e_ignorado(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARIS_MEMORY_ROOT", r"C:\Users\Administrator\ARIS\data\memory")
    monkeypatch.setattr(memcore_paths, "_PROJECT_ROOT", tmp_path / "proj")

    root, _ = memcore_paths.resolve_memory_root()

    assert root == tmp_path / "proj" / "data" / "memory"
    assert [p.name for p in tmp_path.iterdir()] == ["proj"]


@linux_only
def test_memory_db_nao_usa_unidade_D(tmp_path, monkeypatch) -> None:
    from core import memory_db

    monkeypatch.chdir(tmp_path)
    (tmp_path / "D:" / "ARIS_MEMORY").mkdir(parents=True)  # sobra de versões antigas
    monkeypatch.delenv("ARIS_MEMORY_DIR", raising=False)

    resolvido = memory_db._resolve_db_dir()

    assert "D:" not in resolvido.parts
    assert resolvido.parts[-2:] == ("data", "memory")


# ── ferramentas de sistema ────────────────────────────────────────────────


@linux_only
def test_pc_system_status_funciona_sem_powershell() -> None:
    result = pc_tools.pc_system_status()
    assert result["ok"] is True
    assert '"CsName"' in result["stdout"]


@linux_only
def test_pc_processes_lista_processos() -> None:
    result = pc_tools.pc_processes()
    assert result["ok"] is True
    assert str(os.getpid()) in result["stdout"]


@pytest.mark.parametrize("nome", ["Application; Remove-Item x", "App`whoami", "$(calc)", "a|b", ""])
def test_pc_logs_rejeita_nome_de_log_malicioso(nome) -> None:
    result = pc_tools.pc_logs({"log": nome})
    assert result["ok"] is False
    assert "inválido" in result["error"]


def test_pc_logs_rejeita_count_nao_numerico() -> None:
    assert pc_tools.pc_logs({"count": "50; calc"})["ok"] is False


# ── pc_control ────────────────────────────────────────────────────────────


class _Spy(pc_control.PCControl):
    """PCControl que registra o comando em vez de executá-lo."""

    def __init__(self) -> None:
        super().__init__()
        self.argv: list[str] | None = None
        self.ps: str | None = None

    def _run_argv(self, argv, timeout=15):  # type: ignore[override]
        self.argv = list(argv)
        return {"ok": True}

    def _run_ps(self, cmd, timeout=15):  # type: ignore[override]
        self.ps = cmd
        return {"ok": True}


def test_acoes_criticas_continuam_exigindo_confirmacao() -> None:
    spy = _Spy()
    for acao in (spy.pc_shutdown, spy.pc_restart, spy.pc_lock, spy.pc_sleep):
        assert acao({}).get("requires_confirmation") is True
    assert spy.argv is None and spy.ps is None


def test_sem_execucao_real_nada_roda() -> None:
    ctrl = pc_control.PCControl()  # _real_execution=False por padrão
    for acao in (ctrl.pc_shutdown, ctrl.pc_restart, ctrl.pc_lock, ctrl.pc_sleep):
        result = acao({"_confirmed": True})
        assert result["ok"] is False
        assert "disabled" in result["error"]


@linux_only
@pytest.mark.parametrize(
    ("metodo", "params", "esperado"),
    [
        ("pc_shutdown", {}, ["systemctl", "poweroff"]),
        ("pc_shutdown", {"force": True}, ["systemctl", "poweroff", "--force"]),
        ("pc_shutdown", {"timeout_s": 90}, ["shutdown", "-h", "+2"]),
        ("pc_restart", {}, ["systemctl", "reboot"]),
        ("pc_restart", {"timeout_s": 60}, ["shutdown", "-r", "+1"]),
        ("pc_lock", {}, ["loginctl", "lock-session"]),
        ("pc_sleep", {}, ["systemctl", "suspend"]),
    ],
)
def test_pc_control_comandos_linux(metodo, params, esperado) -> None:
    spy = _Spy()
    getattr(spy, metodo)({"_confirmed": True, **params})
    assert spy.argv == esperado
    assert spy.ps is None


def test_pc_control_windows_nao_gera_force_quebrado(monkeypatch) -> None:
    monkeypatch.setattr(pc_control, "_IS_WINDOWS", True)
    spy = _Spy()

    spy.pc_shutdown({"_confirmed": True, "force": True})
    assert spy.ps == "Stop-Computer -Force"  # antes: "Stop-Computer -Force/f"

    spy.pc_restart({"_confirmed": True})
    assert spy.ps == "Restart-Computer"

    spy.pc_shutdown({"_confirmed": True, "timeout_s": 30})
    assert spy.ps == "shutdown /s /t 30"


# ── pc_open_app ───────────────────────────────────────────────────────────


@linux_only
def test_pc_open_app_executa_binario_cadastrado(tmp_path, monkeypatch) -> None:
    from aris_agent.config import AgentConfig
    from aris_agent.contract.types import ToolContext
    from aris_agent.tools import ToolRegistry
    from aris_agent.tools import pc as pacote_pc

    exe = tmp_path / "meuapp"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    chamadas: list[list[str]] = []
    monkeypatch.setattr(
        "subprocess.Popen", lambda argv, **kw: chamadas.append(list(argv)) or object()
    )
    monkeypatch.delattr("os.startfile", raising=False)

    cfg = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        sections={"pc": {"apps": {"meuapp": str(exe)}}},
    )
    ctx = ToolContext(session_id="s", workdir=tmp_path, config=cfg, cancel=threading.Event())
    registry = ToolRegistry()
    pacote_pc.register(registry)

    result = registry.get("pc_open_app").run({"name": "meuapp"}, ctx)

    assert result.ok, result.error
    assert chamadas == [[str(exe)]]


@linux_only
def test_pc_open_app_url_usa_xdg_open(tmp_path, monkeypatch) -> None:
    from aris_agent.tools.pc import apps

    chamadas: list[list[str]] = []
    monkeypatch.delattr("os.startfile", raising=False)
    monkeypatch.setattr(apps.shutil, "which", lambda nome: f"/usr/bin/{nome}")
    monkeypatch.setattr(
        apps.subprocess, "Popen", lambda argv, **kw: chamadas.append(list(argv)) or object()
    )
    monkeypatch.setattr(sys, "platform", "linux")

    assert apps._open_target("https://exemplo.com", executable=False) is None
    assert chamadas == [["/usr/bin/xdg-open", "https://exemplo.com"]]


@linux_only
def test_pc_open_app_sem_xdg_open_explica(monkeypatch) -> None:
    from aris_agent.tools.pc import apps

    monkeypatch.delattr("os.startfile", raising=False)
    monkeypatch.setattr(apps.shutil, "which", lambda nome: None)
    monkeypatch.setattr(sys, "platform", "linux")

    assert "xdg-open" in (apps._open_target("https://x.com", executable=False) or "")


# ── safe_resolve ──────────────────────────────────────────────────────────


@linux_only
@pytest.mark.parametrize("entrada", ["..\\..\\Windows\\System32", "sub\\..\\..\\fora.txt"])
def test_safe_resolve_trata_barra_invertida_como_separador(tmp_path: Path, entrada) -> None:
    with pytest.raises(PathTraversalError):
        safe_resolve(tmp_path, entrada)


def test_safe_resolve_continua_aceitando_caminho_valido(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("ok")
    assert safe_resolve(tmp_path, "a/b.txt").exists()
    assert safe_resolve(tmp_path, "a/../a/b.txt").exists()


# ── EdgeConfig: "~" literal ───────────────────────────────────────────────


def test_edge_config_padrao_expande_o_til() -> None:
    from edge.edge_config import EdgeConfig

    cfg = EdgeConfig()
    assert cfg.memory_dir.is_absolute()
    assert "~" not in cfg.memory_dir.parts
    assert cfg.personality_path.is_absolute()
