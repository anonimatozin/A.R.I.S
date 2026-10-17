"""Testes do chat real do HUD + voice_state (ai-visualizer adaptado).

Cobre (passada funcional):
- send_command armazena histórico usuário + ARIS
- GET /api/hud/chat retorna histórico
- voice_state transita thinking→speaking→idle e expõe formato /state
- chat_message é difundido via SSE (broadcast hook)
"""

import socket
import threading

import pytest

from core.neural.events import Event
from core.vision.hud.server import HUDServer


def _server():
    return HUDServer(host="127.0.0.1", port=8799)


def test_send_command_stores_history_and_responds():
    srv = _server()
    result = srv.send_command("olá")
    assert result["ok"] is True
    assert result["response"]

    chat = srv.get_chat()
    senders = [m["sender"] for m in chat["messages"]]
    assert "VOCÊ" in senders
    assert "ARIS" in senders
    assert chat["messages"][0]["text"] == "olá"


def test_send_command_empty_rejected():
    srv = _server()
    assert srv.send_command("")["ok"] is False
    assert srv.get_chat()["messages"] == []


def test_chat_message_broadcast_via_sse():
    srv = _server()
    seen = []

    class FakeClient:
        def _send_sse_event(self, event_type, data):
            seen.append((event_type, data))

    srv._sse_clients[1] = FakeClient()
    srv.send_command("teste sse")
    types = [t for t, _ in seen]
    assert "chat_message" in types
    assert "aris_status" in types


def test_voice_state_format_matches_visualizer_state():
    srv = _server()
    srv._set_voice_state("thinking")
    state = srv.get_voice_state()
    assert state["state"] == "thinking"
    assert state["loading"] is True
    assert len(state["samples"]) == 64
    assert "level" in state and "alert" in state


def test_voice_state_listening_thinking_speaking_cycle():
    srv = _server()
    srv.publish_external("aris_status", {"state": "listening"})
    assert srv.get_voice_state()["state"] == "listening"
    srv.send_command("ciclo de voz")
    # após ciclo completo volta a idle
    assert srv.get_voice_state()["state"] == "idle"


def test_event_bus_handler_updates_voice_state():
    srv = _server()
    srv._connect_event_bus()
    srv._event_bus.publish(Event(event_type="aris_status", source="test",
                                 payload={"state": "speaking"}))
    assert srv.get_voice_state()["state"] == "speaking"


def test_send_command_passes_history_to_edge():
    # Rota PC: HUD envia histórico como o Discord faz
    import edge.edge_chat as ec

    srv = _server()
    srv.send_command("primeira")
    seen = {}

    class FakeEdge:
        def respond(self, text, origin_info=None):
            seen["text"] = text
            seen["history"] = (origin_info or {}).get("history", [])
            return "ok-fake"

    orig = ec.EdgeChat
    ec.EdgeChat = lambda: FakeEdge()
    try:
        srv.send_command("segunda")
    finally:
        ec.EdgeChat = orig
    assert seen["text"] == "segunda"
    assert any(m["content"] == "primeira" for m in seen["history"])


def test_detect_pc_ip_prefers_localhost():
    # Descoberta local: 127.0.0.1:8770 primeiro (HUD roda no próprio PC)
    import edge.edge_chat as ec

    stop = threading.Event()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", 8770))
    except OSError:
        pytest.skip("porta 8770 ocupada (pc_listener rodando?)")
    listener.listen(1)
    listener.settimeout(5.0)

    def _serve():
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
                conn.close()
            except socket.timeout:
                continue
            except OSError:
                break

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    try:
        ec._cached_pc_ip = None
        assert ec._detect_pc_ip() == "127.0.0.1"
    finally:
        stop.set()
        listener.close()
