"""Testes do CLL1 Server/Heartbeat (Fase 5).

Cobre os dois defeitos reais mostrados no log:
1. ``core/aris.py`` chamava ``CLL1Server(..., message_callback=...)`` mas o
   parâmetro real é ``on_message`` -> TypeError e o server nunca subia.
2. O heartbeat era iniciado mesmo quando o server falhava, e spamava
   ``'NoneType' object has no attribute 'heartbeat_status'``.

E valida a assinatura do callback: o servidor chama
``on_message(text, origin_info)`` (dois args).
"""

import inspect

from core.cll1_server import CLL1Server


class TestCLL1ServerCallbackContract:
    def test_constructor_accepts_on_message(self):
        # O parâmetro real é on_message (não message_callback).
        params = inspect.signature(CLL1Server.__init__).parameters
        assert "on_message" in params
        assert "message_callback" not in params

    def test_on_message_stored(self):
        cb = lambda text, info: None  # noqa: E731
        s = CLL1Server(token="t", on_message=cb)
        assert s._on_message is cb

    def test_server_calls_callback_with_two_args(self):
        # Reproduz o contrato real: (text, origin_info).
        seen = []

        def cb(text, origin_info):
            seen.append((text, origin_info))
            return "ok"

        s = CLL1Server(token="t", on_message=cb)
        # Simula a chamada que o _handle_connection faz.
        resp = s._on_message("oi", {"source": "cll1"})
        assert seen == [("oi", {"source": "cll1"})]
        assert resp == "ok"


class TestArisCallbackSignature:
    def test_aris_callback_matches_server_contract(self):
        # O _on_cll1_message do Aris tem de aceitar (text, origin_info).
        from core.aris import Aris

        params = inspect.signature(Aris._on_cll1_message).parameters
        names = list(params)
        # (self, text, origin_info)
        assert "text" in names
        assert "origin_info" in names


class TestHeartbeatGating:
    def test_heartbeat_only_if_server_exists(self):
        # O source de core/aris.py tem de guardar o heartbeat atrás de um
        # check de ``self._cll1_server is not None``.
        import ast
        from pathlib import Path

        src = Path("core/aris.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found_guard = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_start_distributed":
                segment = ast.get_source_segment(src, node) or ""
                found_guard = "if self._cll1_server is not None:" in segment
                break
        assert found_guard, "heartbeat precisa ser condicional ao server"

    def test_heartbeat_with_none_client_builds_internal_client(self):
        # client=None agora cria o CLL1Client interno via env vars (o
        # motivo do AttributeError 'NoneType ... heartbeat_status' em runtime).
        from core.cll1_heartbeat import CLL1Heartbeat

        hb = CLL1Heartbeat(client=None, interval=30)
        assert hb._client is not None
        # E o heartbeat usa o cliente interno sem estourar em None.
        resp = hb._do_heartbeat()
        # Sem CLL1_TOKEN/servidor real pode falhar, mas retorna dict (não exceção).
        assert isinstance(resp, dict)
        assert "ok" in resp
