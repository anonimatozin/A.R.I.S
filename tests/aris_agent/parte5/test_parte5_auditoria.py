"""Auditoria JSONL: campos, redação, ausência de conteúdo e rotação."""

from __future__ import annotations

import json

from test_parte5_helpers import (  # noqa: F421
    RecordingTool,
    audit_events,
    make_config,
    make_ctx,
    make_executor,
    spec,
    tool_call,
)

from aris_agent.contract.types import Risk
from aris_agent.fakes import AutoConfirm


def test_registro_basico_de_uma_chamada(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor", risk=Risk.READ), content="abc")
    executor = make_executor(config, [tool])
    executor.execute(tool_call("leitor", {"q": "oi"}), make_ctx(config), AutoConfirm())

    eventos = audit_events(config)
    assert len(eventos) == 1
    evento = eventos[0]
    assert isinstance(evento["ts"], float)
    assert evento["session_id"] == "s1"
    assert evento["tool"] == "leitor"
    assert evento["args"] == {"q": "oi"}
    assert evento["risk"] == "READ"
    assert evento["decision"] == "allow"
    assert evento["confirmed"] is None
    assert evento["ok"] is True
    assert evento["error"] is None
    assert evento["resumo"] == "ok, 3 caracteres"
    assert isinstance(evento["duration_ms"], int)
    assert evento["taint"] is False
    assert evento["mode"] == "strict"
    assert evento["injection"] == []


def test_argumentos_com_segredo_sao_redigidos(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor"))
    executor = make_executor(config, [tool])
    executor.execute(
        tool_call(
            "leitor",
            {"password": "abc123", "nota": "api_key=xyz789", "limite": 5},
        ),
        make_ctx(config),
        AutoConfirm(),
    )
    cru = config.audit_log_path.read_text(encoding="utf-8")
    assert "abc123" not in cru
    assert "xyz789" not in cru
    assert "[REDACTED]" in cru
    evento = audit_events(config)[-1]
    assert evento["args"]["password"] == "[REDACTED]"
    assert evento["args"]["limite"] == 5


def test_conteudo_de_arquivo_nao_vai_para_auditoria(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor", path_args=("path",)), content="CONTEUDO-PRIVADO-DO-ARQUIVO")
    executor = make_executor(config, [tool])
    executor.execute(
        tool_call("leitor", {"path": str(config.workspace_dir / "doc.txt")}),
        make_ctx(config),
        AutoConfirm(),
    )
    cru = config.audit_log_path.read_text(encoding="utf-8")
    assert "CONTEUDO-PRIVADO-DO-ARQUIVO" not in cru
    assert json.loads(cru.strip())["resumo"].startswith("ok, ")


def test_preview_opcional_de_saida(tmp_path) -> None:
    config = make_config(tmp_path, audit_preview=True)
    tool = RecordingTool(spec("leitor"), content="CONTEUDO-PRIVADO-DO-ARQUIVO")
    executor = make_executor(config, [tool])
    executor.execute(tool_call("leitor"), make_ctx(config), AutoConfirm())
    evento = audit_events(config)[-1]
    assert "CONTEUDO-PRIVADO-DO-ARQUIVO" in evento["preview"]


def test_segredo_na_saida_nao_aparece_na_auditoria(tmp_path) -> None:
    config = make_config(tmp_path, audit_preview=True)
    tool = RecordingTool(spec("leitor"), content="token gsk_abcdef123456789xyz")
    executor = make_executor(config, [tool])
    executor.execute(tool_call("leitor"), make_ctx(config), AutoConfirm())
    cru = config.audit_log_path.read_text(encoding="utf-8")
    assert "gsk_abcdef" not in cru
    assert "[REDACTED]" in cru


def test_negacao_absoluta_gera_registro(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(
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
    executor = make_executor(config, [tool])
    executor.execute(
        tool_call("shell", {"command": "format D:"}), make_ctx(config), AutoConfirm(True)
    )
    evento = audit_events(config)[-1]
    assert evento["decision"] == "deny"
    assert evento["ok"] is False
    assert "comando negado" in evento["reason"]
    assert "comando negado" in (evento["error"] or "")


def test_ferramenta_com_erro_registrada(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("bomba"), boom=ValueError("x"))
    executor = make_executor(config, [tool])
    executor.execute(tool_call("bomba"), make_ctx(config), AutoConfirm())
    evento = audit_events(config)[-1]
    assert evento["ok"] is False
    assert "ValueError" in (evento["error"] or "")
    assert evento["decision"] == "allow"


def test_rotacao_por_tamanho(tmp_path) -> None:
    config = make_config(tmp_path, audit_max_bytes=100)
    tool = RecordingTool(spec("leitor"))
    executor = make_executor(config, [tool])
    executor.execute(tool_call("leitor", {"i": 1}), make_ctx(config), AutoConfirm())
    executor.execute(tool_call("leitor", {"i": 2}), make_ctx(config), AutoConfirm())
    backup = config.audit_log_path.with_name(config.audit_log_path.name + ".1")
    assert backup.exists()
    assert config.audit_log_path.exists()
    # o backup tem a primeira linha; o arquivo atual tem a segunda
    assert json.loads(backup.read_text(encoding="utf-8").strip())["args"] == {"i": 1}


def test_varias_chamadas_em_ordem(tmp_path) -> None:
    config = make_config(tmp_path)
    tool = RecordingTool(spec("leitor"))
    executor = make_executor(config, [tool])
    for i in range(3):
        executor.execute(tool_call("leitor", {"i": i}), make_ctx(config), AutoConfirm())
    eventos = audit_events(config)
    assert [e["args"]["i"] for e in eventos] == [0, 1, 2]
