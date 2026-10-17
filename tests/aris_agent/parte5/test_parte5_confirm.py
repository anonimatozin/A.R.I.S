"""Confirmação: cli_confirm (timeout = negar) e o pedido feito pelo executor."""

from __future__ import annotations

import time

import pytest
from test_parte5_helpers import (  # noqa: F421
    RecordingTool,
    audit_events,
    make_config,
    make_ctx,
    make_executor,
    spec,
    tool_call,
)

from aris_agent.contract.types import ConfirmRequest, Risk
from aris_agent.fakes import AutoConfirm
from aris_agent.safety import cli_confirm, make_cli_confirm

REQUEST = ConfirmRequest(
    tool_name="shell",
    args_preview="command=dir",
    risk=Risk.EXEC,
    reason="execução de comando requer confirmação",
)


@pytest.mark.parametrize("resposta", ["s", "sim", "S", "y", "yes", "1", "ok"])
def test_cli_confirm_afirmativo(resposta: str) -> None:
    assert cli_confirm(REQUEST, input_fn=lambda _p: resposta) is True


@pytest.mark.parametrize("resposta", ["n", "nao", "não", "", "  ", "sei la", "2"])
def test_cli_confirm_negativo(resposta: str) -> None:
    assert cli_confirm(REQUEST, input_fn=lambda _p: resposta) is False


def test_cli_confirm_timeout_negar() -> None:
    def lento(_prompt: str) -> str:
        time.sleep(3.0)
        return "s"

    inicio = time.monotonic()
    resultado = cli_confirm(REQUEST, input_fn=lento, timeout_s=0.2)
    duracao = time.monotonic() - inicio
    assert resultado is False  # timeout = negar
    assert duracao < 2.0


def test_cli_confirm_erro_de_entrada_negar() -> None:
    def quebra(_prompt: str) -> str:
        raise RuntimeError("entrada quebrada")

    assert cli_confirm(REQUEST, input_fn=quebra) is False


def test_make_cli_confirm_devolve_confirmfn(tmp_path) -> None:
    config = make_config(tmp_path, confirm_timeout_s=1.5)
    confirm = make_cli_confirm(config)
    assert callable(confirm)
    # assinatura ConfirmFn: recebe só o ConfirmRequest (o timeout vem da config)
    assert cli_confirm(REQUEST, input_fn=lambda _p: "s") is True


def _shell() -> RecordingTool:
    return RecordingTool(
        spec(
            "shell",
            risk=Risk.EXEC,
            command_arg="command",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        )
    )


def test_executor_timeout_de_confirmacao_negar(tmp_path) -> None:
    config = make_config(tmp_path, confirm_timeout_s=0.2)
    tool = _shell()
    executor = make_executor(config, [tool])

    def demora(_request) -> bool:
        time.sleep(3.0)
        return True

    inicio = time.monotonic()
    resultado = executor.execute(tool_call("shell", {"command": "notepad"}), make_ctx(config), demora)
    duracao = time.monotonic() - inicio
    assert resultado.ok is False
    assert "timeout" in (resultado.error or "")
    assert duracao < 2.0
    assert tool.calls == []


def test_executor_sem_confirm_fn_nega(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _shell()
    executor = make_executor(config, [tool])
    resultado = executor.execute(tool_call("shell", {"command": "notepad"}), make_ctx(config), None)
    assert resultado.ok is False
    assert "função de confirmação" in (resultado.error or "")
    assert tool.calls == []


def test_confirm_fn_que_lanca_excecao_nega(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _shell()
    executor = make_executor(config, [tool])

    def quebra(_request) -> bool:
        raise ValueError("ui")

    resultado = executor.execute(tool_call("shell", {"command": "notepad"}), make_ctx(config), quebra)
    assert resultado.ok is False
    assert "erro na confirmação" in (resultado.error or "")
    assert tool.calls == []


def test_pedido_de_confirmacao_completo(tmp_path) -> None:
    config = make_config(tmp_path)
    alvo = config.workspace_dir / "pasta"
    alvo.mkdir()
    (alvo / "a.txt").write_text("x", encoding="utf-8")
    tool = RecordingTool(spec("apagador", risk=Risk.DESTRUCTIVE, path_args=("path",)))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    executor.execute(tool_call("apagador", {"path": str(alvo)}), make_ctx(config), confirm)

    pedido = confirm.requests[0]
    assert pedido.tool_name == "apagador"
    assert pedido.risk == Risk.DESTRUCTIVE
    assert pedido.hard_confirm is True
    assert str(alvo) in pedido.args_preview
    assert "1 arquivo(s)" in pedido.args_preview
    assert "destrutiva" in pedido.reason


def test_confirmacao_negada_vai_para_auditoria(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _shell()
    executor = make_executor(config, [tool])
    executor.execute(tool_call("shell", {"command": "notepad"}), make_ctx(config), AutoConfirm(False))
    evento = audit_events(config)[-1]
    assert evento["decision"] == "deny"
    assert evento["confirmed"] is False
    assert "negou" in evento["reason"]


def test_confirmacao_aprovada_vai_para_auditoria(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _shell()
    executor = make_executor(config, [tool])
    executor.execute(tool_call("shell", {"command": "notepad"}), make_ctx(config), AutoConfirm(True))
    evento = audit_events(config)[-1]
    assert evento["decision"] == "confirm"
    assert evento["confirmed"] is True
    assert evento["ok"] is True


def test_format_request_mostra_nivel_forte() -> None:
    from aris_agent.safety import format_request

    texto = format_request(
        ConfirmRequest(
            tool_name="x",
            args_preview="a=1",
            risk=Risk.DESTRUCTIVE,
            reason="algo grave",
            hard_confirm=True,
        )
    )
    assert "CONFIRMAÇÃO OBRIGATÓRIA" in texto
    assert "algo grave" in texto
    assert "[s/N]" in texto
