"""Caminhos hostis: traversal, symlinks, UNC, nomes reservados e cofres."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_parte5_helpers import (  # noqa: F421
    RecordingTool,
    make_config,
    make_ctx,
    make_executor,
    spec,
    tool_call,
)

from aris_agent.contract.types import Risk
from aris_agent.fakes import AutoConfirm


def _writer(config) -> tuple[RecordingTool, object]:
    tool = RecordingTool(spec("escritor", risk=Risk.WRITE, path_args=("path",)))
    return tool, make_executor(config, [tool])


def _reader(config) -> tuple[RecordingTool, object]:
    tool = RecordingTool(spec("leitor", risk=Risk.READ, path_args=("path",)))
    return tool, make_executor(config, [tool])


def test_traversal_relativo_sai_do_workspace(tmp_path) -> None:
    config = make_config(tmp_path)
    tool, executor = _writer(config)
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("escritor", {"path": "../../escapou.txt"}), make_ctx(config), confirm
    )
    assert result.ok is False  # fora das raízes => confirmação (negada aqui)
    assert len(confirm.requests) == 1
    assert tool.calls == []


@pytest.mark.windows  # "..\\..\\..": separador do Windows
def test_traversal_com_retornos(tmp_path) -> None:
    config = make_config(tmp_path)
    tool, executor = _writer(config)
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("escritor", {"path": "..\\..\\escapou2.txt"}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert len(confirm.requests) == 1


def test_traversal_resolvido_dentro_permite(tmp_path) -> None:
    """ws/sub/../dentro.txt resolve para dentro => automático."""
    config = make_config(tmp_path)
    (config.workspace_dir / "sub").mkdir(exist_ok=True)
    tool, executor = _writer(config)
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("escritor", {"path": "sub\\..\\dentro.txt"}), make_ctx(config), confirm
    )
    assert result.ok is True
    assert confirm.requests == []


def test_link_simbolico_para_fora_nao_conta_como_interno(tmp_path) -> None:
    config = make_config(tmp_path)
    fora = tmp_path / "fora"
    fora.mkdir(exist_ok=True)
    link = config.workspace_dir / "link"
    try:
        os.symlink(str(fora), str(link), target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink indisponível neste ambiente: {exc}")
    tool, executor = _writer(config)
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("escritor", {"path": str(link / "dentro.txt")}), make_ctx(config), confirm
    )
    assert result.ok is False  # resolve para fora => confirmação
    assert len(confirm.requests) == 1
    assert str(fora.resolve()) in confirm.requests[0].args_preview or "fora das raízes" in (
        confirm.requests[0].reason
    )


@pytest.mark.windows  # caminho UNC (\\servidor\compartilhamento)
def test_caminho_unc_fora_das_raizes(tmp_path) -> None:
    config = make_config(tmp_path)
    tool, executor = _writer(config)
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("escritor", {"path": "\\\\no-such-host-aris\\share\\x.txt"}),
        make_ctx(config),
        confirm,
    )
    assert result.ok is False  # UNC nunca está nas raízes => confirmação
    assert len(confirm.requests) == 1
    assert tool.calls == []


@pytest.mark.parametrize("reservado", ["CON", "NUL", "PRN", "AUX", "COM1", "LPT1", "con.txt"])
def test_nome_reservado_do_windows_negado(tmp_path, reservado: str) -> None:
    config = make_config(tmp_path)
    tool, executor = _writer(config)
    confirm = AutoConfirm(True)
    result = executor.execute(
        tool_call("escritor", {"path": reservado}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert "nome reservado" in (result.error or "")
    assert confirm.requests == []
    assert tool.calls == []


def test_namespace_de_dispositivo_negado(tmp_path) -> None:
    config = make_config(tmp_path)
    tool, executor = _writer(config)
    confirm = AutoConfirm(True)
    result = executor.execute(
        tool_call("escritor", {"path": "\\\\.\\PhysicalDrive0"}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert "dispositivo" in (result.error or "")
    assert confirm.requests == []


def test_prefixo_extendido_e_tratado_como_caminho_normal(tmp_path) -> None:
    config = make_config(tmp_path)
    tool, executor = _writer(config)
    confirm = AutoConfirm(False)
    alvo = config.workspace_dir / "ok.txt"
    result = executor.execute(
        tool_call("escritor", {"path": "\\\\?\\" + str(alvo)}), make_ctx(config), confirm
    )
    assert result.ok is True
    assert confirm.requests == []


@pytest.mark.windows  # comparação case-insensitive de drive ("c:\" vs "C:\")
def test_caixa_diferente_continua_dentro(tmp_path) -> None:
    config = make_config(tmp_path)
    tool, executor = _writer(config)
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("escritor", {"path": str(config.workspace_dir).upper() + "\\NOVO.TXT"}),
        make_ctx(config),
        confirm,
    )
    assert result.ok is True
    assert confirm.requests == []


def test_prefixo_parecido_nao_conta_como_interno(tmp_path) -> None:
    """C:\\workspace2 não está dentro de C:\\workspace (comparação por partes)."""
    config = make_config(tmp_path)
    irma = tmp_path / "workspace2"
    irma.mkdir(exist_ok=True)
    tool, executor = _writer(config)
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("escritor", {"path": str(irma / "x.txt")}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert len(confirm.requests) == 1


@pytest.mark.parametrize(
    "relativo",
    [".env", ".env.local", ".ssh\\id_rsa", "chaves\\servidor.pem", "backup.kdbx"],
)
def test_cofres_negados_mesmo_dentro_do_workspace(tmp_path, relativo: str) -> None:
    config = make_config(tmp_path)
    tool, executor = _reader(config)
    confirm = AutoConfirm(True)
    result = executor.execute(
        tool_call("leitor", {"path": str(config.workspace_dir / relativo)}),
        make_ctx(config),
        confirm,
    )
    assert result.ok is False
    assert "negado" in (result.error or "")
    assert confirm.requests == []


def test_perfil_de_navegador_negado(tmp_path) -> None:
    config = make_config(tmp_path)
    tool, executor = _reader(config)
    confirm = AutoConfirm(True)
    perfil = (
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Cookies"
    )
    result = executor.execute(tool_call("leitor", {"path": str(perfil)}), make_ctx(config), confirm)
    assert result.ok is False
    assert "credenciais" in (result.error or "")
    assert confirm.requests == []


def test_leitura_fora_do_workspace_e_permitida(tmp_path) -> None:
    """READ fora das raízes é automático por definição (limitação documentada)."""
    config = make_config(tmp_path)
    tool, executor = _reader(config)
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("leitor", {"path": str(tmp_path / "qualquer.txt")}), make_ctx(config), confirm
    )
    assert result.ok is True
    assert confirm.requests == []
