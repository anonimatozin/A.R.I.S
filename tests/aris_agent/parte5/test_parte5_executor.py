"""Núcleo do SafeExecutor: protocolo, exceções, timeout, cancel e redação."""

from __future__ import annotations

import threading
import time

from test_parte5_helpers import (  # noqa: F421
    RecordingTool,
    make_config,
    make_ctx,
    make_executor,
    spec,
    tool_call,
)

from aris_agent.contract.protocols import ToolExecutor
from aris_agent.contract.types import Risk, ToolResult
from aris_agent.fakes import AutoConfirm


def test_implementa_o_protocolo_tool_executor(tmp_path) -> None:
    config = make_config(tmp_path)
    executor = make_executor(config, [RecordingTool(spec("leitor"))])
    assert isinstance(executor, ToolExecutor)


def test_excecao_da_ferramenta_vira_resultado(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("bomba"), boom=RuntimeError("deu ruim"))
    executor = make_executor(config, [tool])
    resultado = executor.execute(tool_call("bomba"), make_ctx(config), AutoConfirm())
    assert resultado.ok is False
    assert "RuntimeError" in (resultado.error or "")
    assert "deu ruim" in (resultado.error or "")


def test_retorno_invalido_vira_erro(tmp_path) -> None:
    config = make_config(tmp_path)

    class Estranha:
        spec = spec("estranha")

        def run(self, args, ctx):  # type: ignore[no-untyped-def]
            return "não sou ToolResult"

    executor = make_executor(config, [Estranha()])
    resultado = executor.execute(tool_call("estranha"), make_ctx(config), AutoConfirm())
    assert resultado.ok is False
    assert "em vez de ToolResult" in (resultado.error or "")


def test_timeout_da_ferramenta(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("lenta", timeout_s=0.15), delay=2.0)
    executor = make_executor(config, [tool])
    inicio = time.monotonic()
    resultado = executor.execute(tool_call("lenta"), make_ctx(config), AutoConfirm())
    duracao = time.monotonic() - inicio
    assert resultado.ok is False
    assert "timeout" in (resultado.error or "")
    assert duracao < 1.5


def test_cancel_no_meio_da_execucao(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("lenta", timeout_s=10.0), delay=1.5)
    executor = make_executor(config, [tool])
    ctx = make_ctx(config)
    caixa: dict = {}

    def rodar() -> None:
        caixa["r"] = executor.execute(tool_call("lenta"), ctx, AutoConfirm())

    threads = threading.Thread(target=rodar, daemon=True)
    threads.start()
    time.sleep(0.2)
    ctx.cancel.set()
    threads.join(timeout=5.0)
    assert not threads.is_alive()
    assert caixa["r"].ok is False
    assert "cancelado" in (caixa["r"].error or "")


def test_segredos_redigidos_na_saida(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor"), content="resultado: minha_senha=SuperSecret123 ok")
    executor = make_executor(config, [tool])
    resultado = executor.execute(tool_call("leitor"), make_ctx(config), AutoConfirm())
    assert resultado.ok is True
    assert "SuperSecret123" not in resultado.content
    assert "[REDACTED]" in resultado.content


def test_chave_de_api_na_saida_redigida(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor"), content="token gsk_abcdef1234567890xyz")
    executor = make_executor(config, [tool])
    resultado = executor.execute(tool_call("leitor"), make_ctx(config), AutoConfirm())
    assert "gsk_abcdef" not in resultado.content
    assert "[REDACTED]" in resultado.content


def test_erro_com_segredo_tambem_redigido(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor"), ok=False, error="falhou com api_key=gsk_abc123def456")
    executor = make_executor(config, [tool])
    resultado = executor.execute(tool_call("leitor"), make_ctx(config), AutoConfirm())
    assert resultado.ok is False
    assert "gsk_abc123def456" not in (resultado.error or "")
    assert "[REDACTED]" in (resultado.error or "")


def test_saida_longa_e_truncada(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor"), content="x" * 20000)
    executor = make_executor(config, [tool])
    resultado = executor.execute(tool_call("leitor"), make_ctx(config), AutoConfirm())
    assert len(resultado.content) <= 8000
    assert "caracteres omitidos" in resultado.content


def test_data_e_artifacts_passam_intactos(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(
        spec("produtor"),
        content="ok",
        result_fn=lambda args, ctx: ToolResult(
            ok=True, content="ok", data={"n": 1}, artifacts=["a.txt"]
        ),
    )
    executor = make_executor(config, [tool])
    resultado = executor.execute(tool_call("produtor"), make_ctx(config), AutoConfirm())
    assert resultado.data == {"n": 1}
    assert resultado.artifacts == ["a.txt"]


def test_secao_safety_invalida_cai_no_padrao(tmp_path) -> None:
    config = make_config(tmp_path, mode="qualquer_coisa", exec_per_minute="abc")
    executor = make_executor(config, [RecordingTool(spec("leitor"))])
    assert executor.settings.mode == "strict"
    assert executor.settings.exec_per_minute == 10
    resultado = executor.execute(tool_call("leitor"), make_ctx(config), AutoConfirm())
    assert resultado.ok is True


def test_risk_destructive_nunca_fica_abaixo(tmp_path) -> None:
    """Nenhum modo/allowlist rebaixa DESTRUCTIVE para allow automático."""
    config = make_config(tmp_path, mode="balanced", exec_allowlist=["apagador"])
    tool = RecordingTool(spec("apagador", risk=Risk.DESTRUCTIVE, path_args=("path",)))
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(True)
    resultado = executor.execute(
        tool_call("apagador", {"path": str(config.workspace_dir / "x.txt")}),
        make_ctx(config),
        confirm,
    )
    assert resultado.ok is True  # confirmou (hard) e rodou
    assert confirm.requests[0].hard_confirm is True
