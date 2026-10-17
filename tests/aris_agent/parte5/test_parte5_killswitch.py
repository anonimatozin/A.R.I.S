"""KillSwitch: arquivo-sentinela, engage/reset e atalho opcional."""

from __future__ import annotations

import sys
import threading

from test_parte5_helpers import (  # noqa: F421
    RecordingTool,
    make_config,
    make_ctx,
    make_executor,
    spec,
    tool_call,
)

from aris_agent.fakes import AutoConfirm
from aris_agent.safety import KillSwitch


def _tool() -> RecordingTool:
    return RecordingTool(spec("leitor"))


def test_arquivo_sentinela_bloqueia_e_cancela(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    ctx = make_ctx(config)
    confirm = AutoConfirm(False)

    primeira = executor.execute(tool_call("leitor", {}), ctx, confirm)
    assert primeira.ok is True
    assert executor.kill_switch.engaged is False

    (config.data_dir / "STOP").write_text("parar", encoding="utf-8")
    segunda = executor.execute(tool_call("leitor", {"q": "2"}), ctx, confirm)

    assert segunda.ok is False
    assert "kill switch" in (segunda.error or "")
    assert executor.kill_switch.engaged is True
    assert "STOP" in executor.kill_switch.reason
    assert ctx.cancel.is_set()  # cancel da tarefa registrada foi setado
    assert len(tool.calls) == 1


def test_reset_remove_sentinela_e_libera_novas_chamadas(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)

    (config.data_dir / "STOP").touch()
    bloqueada = executor.execute(tool_call("leitor", {}), make_ctx(config), confirm)
    assert bloqueada.ok is False

    executor.kill_switch.reset()
    assert executor.kill_switch.engaged is False
    assert not (config.data_dir / "STOP").exists()

    liberada = executor.execute(tool_call("leitor", {"q": "novo"}), make_ctx(config), confirm)
    assert liberada.ok is True


def test_engage_metodo_python(tmp_path) -> None:
    config = make_config(tmp_path)
    executor = make_executor(config, [_tool()])
    assert executor.kill_switch.engage("teste manual") is True
    assert executor.kill_switch.engage("outra vez") is False  # já ativo
    resultado = executor.execute(tool_call("leitor", {}), make_ctx(config), AutoConfirm())
    assert resultado.ok is False
    assert "teste manual" in (resultado.error or "")
    assert "novas chamadas bloqueadas" in (resultado.error or "")


def test_register_cancela_na_hora_se_ja_ativo(tmp_path) -> None:
    kill = KillSwitch(tmp_path)
    kill.engage("teste")
    cancel = threading.Event()
    kill.register(cancel)
    assert cancel.is_set()


def test_ctx_cancelado_antes_ja_nao_executa(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _tool()
    executor = make_executor(config, [tool])
    ctx = make_ctx(config)
    ctx.cancel.set()
    resultado = executor.execute(tool_call("leitor", {}), ctx, AutoConfirm())
    assert resultado.ok is False
    assert "antes da execução" in (resultado.error or "")
    assert tool.calls == []


def test_hotkey_desligado_por_padrao(tmp_path) -> None:
    kill = KillSwitch(tmp_path)
    assert kill.start_hotkey() is False  # enable_hotkey=False => nem tenta importar


def test_hotkey_ligado_sem_biblioteca_avisa(tmp_path, monkeypatch, caplog) -> None:
    import logging

    monkeypatch.setitem(sys.modules, "keyboard", None)  # import falha de forma determinística
    caplog.set_level(logging.DEBUG, logger="aris.agent.safety.killswitch")
    config = make_config(tmp_path, enable_hotkey=True)
    executor = make_executor(config, [_tool()])
    mensagens = " ".join(r.getMessage() for r in caplog.records)
    assert "keyboard" in mensagens
    assert executor.kill_switch.engaged is False
    resultado = executor.execute(tool_call("leitor", {}), make_ctx(config), AutoConfirm())
    assert resultado.ok is True
