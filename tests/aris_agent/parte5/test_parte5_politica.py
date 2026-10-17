"""Política por risco: READ/WRITE/EXEC/DESTRUCTIVE, modos e ações em lote."""

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


def _exec_tool(name: str = "exec_cmd", command: str = "command") -> RecordingTool:
    return RecordingTool(
        spec(
            name,
            risk=Risk.EXEC,
            command_arg=command,
            parameters={
                "type": "object",
                "properties": {command: {"type": "string"}},
                "required": [command],
            },
        )
    )


# ------------------------------------------------------------------ READ/WRITE


def test_read_e_automatico(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor", risk=Risk.READ, path_args=("path",)))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("leitor", {"path": str(tmp_path / "fora" / "a.txt")}), make_ctx(config), confirm
    )
    assert result.ok is True
    assert confirm.requests == []
    assert len(tool.calls) == 1


def test_write_dentro_das_raizes_e_automatico(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("escritor", risk=Risk.WRITE, path_args=("path",)))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    destino = config.workspace_dir / "nota.txt"
    result = executor.execute(tool_call("escritor", {"path": str(destino)}), make_ctx(config), confirm)
    assert result.ok is True
    assert confirm.requests == []


def test_write_fora_das_raizes_pede_confirmacao(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("escritor", risk=Risk.WRITE, path_args=("path",)))
    executor = make_executor(config, [tool])
    alvo = str(tmp_path / "fora.txt")

    negado = AutoConfirm(False)
    result = executor.execute(tool_call("escritor", {"path": alvo}), make_ctx(config), negado)
    assert result.ok is False
    assert "negou" in (result.error or "")
    assert len(negado.requests) == 1
    assert "fora das raízes" in negado.requests[0].reason

    autorizado = AutoConfirm(True)
    result = executor.execute(tool_call("escritor", {"path": alvo}), make_ctx(config), autorizado)
    assert result.ok is True
    assert len(tool.calls) == 1


def test_write_sem_caminho_verificavel_confirma(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("clipboard", risk=Risk.WRITE))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(tool_call("clipboard", {"texto": "oi"}), make_ctx(config), confirm)
    assert result.ok is False
    assert len(confirm.requests) == 1
    assert "sem caminho verificável" in confirm.requests[0].reason


# ----------------------------------------------------------------------- EXEC


def test_exec_ped_confirmacao_por_padrao(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _exec_tool()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(tool_call("exec_cmd", {"command": "notepad x.txt"}), make_ctx(config), confirm)
    assert result.ok is False
    assert len(confirm.requests) == 1
    assert confirm.requests[0].risk == Risk.EXEC
    assert tool.calls == []


def test_exec_na_lista_de_permissao_nao_confirma(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _exec_tool()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(tool_call("exec_cmd", {"command": "dir"}), make_ctx(config), confirm)
    assert result.ok is True
    assert confirm.requests == []
    assert len(tool.calls) == 1


def test_exec_por_nome_de_ferramenta_na_lista(tmp_path) -> None:
    config = make_config(tmp_path, exec_allowlist=["pc_open_app"])
    tool = RecordingTool(spec("pc_open_app", risk=Risk.EXEC))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(tool_call("pc_open_app", {"app": "calc"}), make_ctx(config), confirm)
    assert result.ok is True
    assert confirm.requests == []


def test_exec_prefixo_da_lista(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _exec_tool()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("exec_cmd", {"command": "git status --short"}), make_ctx(config), confirm
    )
    assert result.ok is True
    assert confirm.requests == []


# -------------------------------------------------------------- DESTRUCTIVE


def test_destructive_sempre_confirma_forte(tmp_path) -> None:
    config = make_config(tmp_path)
    alvo = config.workspace_dir / "apagar"
    alvo.mkdir()
    (alvo / "a.txt").write_text("x", encoding="utf-8")
    (alvo / "b.txt").write_text("y", encoding="utf-8")
    tool = RecordingTool(spec("apagador", risk=Risk.DESTRUCTIVE, path_args=("path",)))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(tool_call("apagador", {"path": str(alvo)}), make_ctx(config), confirm)
    assert result.ok is False
    assert len(confirm.requests) == 1
    request = confirm.requests[0]
    assert request.hard_confirm is True
    assert request.risk == Risk.DESTRUCTIVE
    assert "alvos resolvidos" in request.args_preview
    assert "2 arquivo(s)" in request.args_preview
    assert tool.calls == []


def test_comando_destrutivo_sobe_o_risco(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _exec_tool()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("exec_cmd", {"command": "del nota.txt"}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert len(confirm.requests) == 1
    assert confirm.requests[0].hard_confirm is True
    assert confirm.requests[0].risk == Risk.DESTRUCTIVE


# --------------------------------------------------------------------- MODOS


def test_readonly_so_permite_read(tmp_path) -> None:
    config = make_config(tmp_path, mode="readonly")
    leitor = RecordingTool(spec("leitor", risk=Risk.READ))
    escritor = RecordingTool(spec("escritor", risk=Risk.WRITE, path_args=("path",)))
    executor = make_executor(config, [leitor, escritor])
    confirm = AutoConfirm(True)

    ok = executor.execute(tool_call("leitor", {}), make_ctx(config), confirm)
    assert ok.ok is True

    result = executor.execute(
        tool_call("escritor", {"path": str(config.workspace_dir / "a.txt")}),
        make_ctx(config),
        confirm,
    )
    assert result.ok is False
    assert "somente leitura" in (result.error or "")
    assert confirm.requests == []
    assert escritor.calls == []


def test_readonly_nao_desliga_negacao_absoluta(tmp_path) -> None:
    config = make_config(tmp_path, mode="readonly")
    tool = _exec_tool()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(True)
    result = executor.execute(
        tool_call("exec_cmd", {"command": "format D:"}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert "comando negado" in (result.error or "")
    assert confirm.requests == []


def test_balanced_permite_script_dentro_do_workspace(tmp_path) -> None:
    script = config_workspace_script(tmp_path)
    comando = f"python {script}"

    estrito = make_config(tmp_path, mode="strict")
    tool_s = _exec_tool()
    exec_s = make_executor(estrito, [tool_s])
    confirm_s = AutoConfirm(False)
    exec_s.execute(tool_call("exec_cmd", {"command": comando}), make_ctx(estrito), confirm_s)
    assert len(confirm_s.requests) == 1  # strict confirma

    balanced = make_config(tmp_path, mode="balanced")
    tool_b = _exec_tool()
    exec_b = make_executor(balanced, [tool_b])
    confirm_b = AutoConfirm(False)
    result = exec_b.execute(tool_call("exec_cmd", {"command": comando}), make_ctx(balanced), confirm_b)
    assert result.ok is True
    assert confirm_b.requests == []


def test_balanced_nao_permite_python_c(tmp_path) -> None:
    config = make_config(tmp_path, mode="balanced")
    tool = _exec_tool()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("exec_cmd", {"command": 'python -c "print(1)"'}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert len(confirm.requests) == 1


def config_workspace_script(tmp_path) -> str:
    """Cria um .py dentro do workspace e devolve o caminho."""
    config = make_config(tmp_path)
    script = config.workspace_dir / "tarefa.py"
    script.write_text("print(1)", encoding="utf-8")
    return str(script)


# ---------------------------------------------------------------- AÇÃO EM LOTE


def test_lote_muitos_caminhos_confirma_forte(tmp_path) -> None:
    config = make_config(tmp_path, batch_path_threshold=5)
    tool = RecordingTool(
        spec(
            "escritor",
            risk=Risk.WRITE,
            path_args=("paths",),
            parameters={
                "type": "object",
                "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
                "required": ["paths"],
            },
        )
    )
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    caminhos = [str(config.workspace_dir / f"f{i}.txt") for i in range(6)]
    result = executor.execute(tool_call("escritor", {"paths": caminhos}), make_ctx(config), confirm)
    assert result.ok is False
    assert len(confirm.requests) == 1
    assert confirm.requests[0].hard_confirm is True
    assert "ação em lote" in confirm.requests[0].reason


def test_lote_por_curinga_confirma_forte(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor", risk=Risk.WRITE, path_args=("path",)))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("leitor", {"path": str(config.workspace_dir / "*")}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert confirm.requests[0].hard_confirm is True
    assert "curinga" in confirm.requests[0].reason


def test_lote_por_texto_geral_confirma_forte(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("email", risk=Risk.WRITE))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("email", {"filtro": "todos os e-mails"}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert confirm.requests[0].hard_confirm is True
    assert "ação em lote" in confirm.requests[0].reason


def test_lote_alvo_protegido_e_negado(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("escritor", risk=Risk.WRITE, path_args=("path",)))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(True)
    result = executor.execute(
        tool_call("escritor", {"path": str(Path.home())}), make_ctx(config), confirm
    )
    assert result.ok is False
    assert "pasta do usuário" in (result.error or "")
    assert confirm.requests == []
    assert tool.calls == []


# ---------------------------------------------------------- ÁREAS PROTEGIDAS


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        pytest.param(lambda: str(Path(Path.home().anchor)), "raiz de disco", id="raiz_disco"),
        pytest.param(lambda: str(Path.home()), "pasta do usuário", id="pasta_usuario"),
        pytest.param(lambda: os.environ.get("windir", r"C:\Windows"), "pasta de sistema", id="windir", marks=pytest.mark.windows),
        pytest.param(lambda: str(Path.home().parent), "pasta de usuários", id="pasta_users"),
    ],
)
def test_write_em_area_protegida_negado(tmp_path, valor, esperado) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("escritor", risk=Risk.WRITE, path_args=("path",)))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(True)
    result = executor.execute(tool_call("escritor", {"path": valor()}), make_ctx(config), confirm)
    assert result.ok is False
    assert esperado in (result.error or "")
    assert confirm.requests == []


def test_read_da_pasta_do_usuario_e_permitido(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor", risk=Risk.READ, path_args=("path",)))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    result = executor.execute(
        tool_call("leitor", {"path": str(Path.home())}), make_ctx(config), confirm
    )
    assert result.ok is True
    assert confirm.requests == []
