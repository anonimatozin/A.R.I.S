"""Trava de lista fixa do bridge de controle do PC (pc_listener :8770).

Regra de entrega: pedir uma ação fora da lista → o bridge recusa
(nunca executa código/comando livre).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import threading
import urllib.request

from agent.pc_actions import ALLOWED_COMMANDS, build_pc_payload, validate_body

# ── Validação (fonte única da trava) ───────────────────────

def test_exec_nao_esta_na_lista():
    assert "exec" not in ALLOWED_COMMANDS


def test_exec_payload_recusado():
    ok, error = validate_body(
        {"command": "exec", "code": "import os; os.system('del /f /q C:\\\\*')"}
    )
    assert ok is False
    assert "lista" in error


def test_comando_desconhecido_recusado():
    ok, error = validate_body({"command": "format_drive"})
    assert ok is False
    assert "format_drive" in error


def test_run_command_do_llm_nunca_vira_payload():
    payload = build_pc_payload("run_command", {"command": "rm -rf /"})
    assert payload is None


def test_builder_so_gera_acoes_da_lista():
    casos = [
        ("shutdown", {}),
        ("restart", {}),
        ("lock", {}),
        ("sleep", {}),
        ("system_status", {}),
        ("cancel_schedule", {}),
        ("open_app", {"app": "notepad"}),
        ("open_browser", {}),
        ("search_web", {"query": "aris"}),
        ("schedule_shutdown", {"at": "23:30"}),
        ("schedule_wake", {"at": "07:00"}),
    ]
    for action_type, params in casos:
        payload = build_pc_payload(action_type, params)
        assert payload is not None, action_type
        ok, err = validate_body(payload)
        assert ok, f"{action_type}: {err}"
        assert payload["command"] in ALLOWED_COMMANDS


def test_url_nao_http_recusada():
    for url in ("file:///C:/Windows", "javascript:alert(1)", "ftp://x", 'http://x"y'):
        ok, _ = validate_body({"command": "open_url", "url": url})
        assert ok is False, url


def test_target_com_metacaractera_recusado():
    ok, _ = validate_body(
        {"command": "open_app", "target": "notepad & del /f /q C:\\*"}
    )
    assert ok is False


def test_horario_fora_de_intervalo_recusado():
    ok, _ = validate_body({"command": "schedule_shutdown", "at": "25:99"})
    assert ok is False
    ok, _ = validate_body({"command": "schedule_shutdown", "at": "23:59"})
    assert ok is True
    ok, _ = validate_body(
        {"command": "schedule_wake", "at": "2026-09-27 07:30"}
    )
    assert ok is True


def test_acoes_legitimas_passam():
    for body in (
        {"command": "status"},
        {"command": "shutdown"},
        {"command": "restart"},
        {"command": "lock"},
        {"command": "sleep"},
        {"command": "browser_screenshot"},
        {"command": "schedule_query"},
    ):
        ok, err = validate_body(body)
        assert ok, f"{body}: {err}"


# ── Bridge HTTP de verdade (porta efêmera) ─────────────────

def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _bridge_server():
    from http.server import HTTPServer

    from agent.pc_listener import CmdHandler

    server = HTTPServer(("127.0.0.1", 0), CmdHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_bridge_recusa_exec_de_codigo_livre():
    server, thread = _bridge_server()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        result = _post(url, {"command": "exec", "code": "print('pwned')"})
        assert result["ok"] is False
        assert "lista" in result["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_bridge_recusa_acao_fora_da_lista():
    server, thread = _bridge_server()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        result = _post(url, {"command": "delete_everything"})
        assert result["ok"] is False
        assert "lista" in result["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_bridge_aceita_acao_da_lista():
    server, thread = _bridge_server()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        result = _post(url, {"command": "status"})
        assert result == {"ok": True, "pc": "online"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_bridge_recusa_url_file_no_open_url():
    server, thread = _bridge_server()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        result = _post(url, {"command": "open_url", "url": "file:///C:/Windows"})
        assert result["ok"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
