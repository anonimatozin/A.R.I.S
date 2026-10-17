"""Proteções de laço: repetição 3x, limites por minuto e por tarefa."""

from __future__ import annotations

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


def _leitor() -> RecordingTool:
    return RecordingTool(spec("leitor", risk=Risk.READ))


def test_repeticao_tres_vezes_e_bloqueada(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _leitor()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    ctx = make_ctx(config)

    primeira = executor.execute(tool_call("leitor", {"q": "mesma"}), ctx, confirm)
    segunda = executor.execute(tool_call("leitor", {"q": "mesma"}), ctx, confirm)
    terceira = executor.execute(tool_call("leitor", {"q": "mesma"}), ctx, confirm)
    quarta = executor.execute(tool_call("leitor", {"q": "mesma"}), ctx, confirm)

    assert primeira.ok and segunda.ok
    assert terceira.ok is False
    assert "repetida 3 vezes" in (terceira.error or "")
    assert "mude de estratégia" in (terceira.error or "")
    assert quarta.ok is False
    assert len(tool.calls) == 2


def test_argumentos_diferentes_resetam_a_repeticao(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = _leitor()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)
    ctx = make_ctx(config)

    for valor in ("a", "b", "c", "a", "b"):
        result = executor.execute(tool_call("leitor", {"q": valor}), ctx, confirm)
        assert result.ok is True
    # volta a "a": a sequência diferente zera o contador, então 2ª e 3ª seguem
    assert executor.execute(tool_call("leitor", {"q": "a"}), ctx, confirm).ok is True
    assert executor.execute(tool_call("leitor", {"q": "a"}), ctx, confirm).ok is True
    assert executor.execute(tool_call("leitor", {"q": "a"}), ctx, confirm).ok is False
    assert len(tool.calls) == 7


def test_repeticao_configuravel(tmp_path) -> None:
    config = make_config(tmp_path, repeat_limit=2)
    tool = _leitor()
    executor = make_executor(config, [tool])
    ctx = make_ctx(config)
    assert executor.execute(tool_call("leitor", {}), ctx, AutoConfirm()).ok is True
    resultado = executor.execute(tool_call("leitor", {}), ctx, AutoConfirm())
    assert resultado.ok is False
    assert "repetida 2 vezes" in (resultado.error or "")


def test_limite_por_minuto(tmp_path) -> None:
    config = make_config(tmp_path, exec_per_minute=2, exec_per_task=100)
    tool = _shell()
    executor = make_executor(config, [tool])
    ctx = make_ctx(config)
    confirm = AutoConfirm(False)

    ok1 = executor.execute(tool_call("shell", {"command": "dir C:\\a"}), ctx, confirm)
    ok2 = executor.execute(tool_call("shell", {"command": "dir C:\\b"}), ctx, confirm)
    bloqueada = executor.execute(tool_call("shell", {"command": "dir C:\\c"}), ctx, confirm)

    assert ok1.ok and ok2.ok
    assert bloqueada.ok is False
    assert "por minuto" in (bloqueada.error or "")
    assert len(tool.calls) == 2


def test_limite_por_tarefa(tmp_path) -> None:
    config = make_config(tmp_path, exec_per_minute=100, exec_per_task=3)
    tool = _shell()
    executor = make_executor(config, [tool])
    ctx = make_ctx(config)
    confirm = AutoConfirm(False)

    resultados = [
        executor.execute(tool_call("shell", {"command": f"dir C:\\{i}"}), ctx, confirm)
        for i in range(4)
    ]
    assert [r.ok for r in resultados] == [True, True, True, False]
    assert "por tarefa" in (resultados[-1].error or "")
    assert len(tool.calls) == 3


def test_reads_nao_contam_para_o_limite_de_exec(tmp_path) -> None:
    config = make_config(tmp_path, exec_per_task=2, exec_per_minute=100)
    shell = _shell()
    leitor = _leitor()
    executor = make_executor(config, [shell, leitor])
    ctx = make_ctx(config)
    confirm = AutoConfirm(False)

    for i in range(5):
        executor.execute(tool_call("leitor", {"i": i}), ctx, confirm)
    exec1 = executor.execute(tool_call("shell", {"command": "dir C:\\a"}), ctx, confirm)
    exec2 = executor.execute(tool_call("shell", {"command": "dir C:\\b"}), ctx, confirm)
    exec3 = executor.execute(tool_call("shell", {"command": "dir C:\\c"}), ctx, confirm)

    assert exec1.ok and exec2.ok
    assert exec3.ok is False
    assert "por tarefa" in (exec3.error or "")
    assert len(leitor.calls) == 5
    assert len(shell.calls) == 2


def test_sessoes_diferentes_tem_limite_separado(tmp_path) -> None:
    config = make_config(tmp_path, exec_per_task=1, exec_per_minute=100)
    tool = _shell()
    executor = make_executor(config, [tool])
    confirm = AutoConfirm(False)

    primeira = executor.execute(
        tool_call("shell", {"command": "dir C:\\x"}), make_ctx(config, session_id="s1"), confirm
    )
    outra = executor.execute(
        tool_call("shell", {"command": "dir C:\\y"}), make_ctx(config, session_id="s2"), confirm
    )
    assert primeira.ok
    assert outra.ok  # outro session_id => outro contador de tarefa
