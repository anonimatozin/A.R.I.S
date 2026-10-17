"""Watcher do túnel + separação dashboard x scheduler (sem rede real)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gateway import tunnel_watcher as tw
from gateway.tunnel_config import (
    TUNNEL_TARGET_PORT, SCHEDULER_PORT, TUNNEL_FORBIDDEN_PORTS, tunnel_target,
)


def _tmp_base(monkeypatch=None):
    d = tempfile.mkdtemp()
    return d


def test_cloudflared_parses_last_url(tmp_path):
    log = tmp_path / "tunnel_live.err"
    log.write_text(
        "2026-09-19 INF |  https://aaa-bbb-ccc.trycloudflare.com  |\n"
        "2026-09-19 INF Registered tunnel connection\n"
        "2026-09-19 INF |  https://ddd-eee-fff.trycloudflare.com  |\n",
        encoding="utf-8",
    )
    assert tw.get_cloudflared_url(log) == "https://ddd-eee-fff.trycloudflare.com"


def test_cloudflared_missing_log_returns_none(tmp_path):
    assert tw.get_cloudflared_url(tmp_path / "nope.err") is None


def test_no_change_no_notify(tmp_path):
    base = str(tmp_path)
    tw.save_last("https://x.trycloudflare.com", "cloudflared", base)
    calls = []
    orig = tw.get_current_url
    tw.get_current_url = lambda: ("https://x.trycloudflare.com", "cloudflared")
    try:
        r = tw.check_once(base, notify=lambda m: calls.append(m) or True)
    finally:
        tw.get_current_url = orig
    assert r["changed"] is False
    assert calls == []


def test_change_notifies_with_new_url(tmp_path):
    base = str(tmp_path)
    tw.save_last("https://old.trycloudflare.com", "cloudflared", base)
    calls = []
    orig = tw.get_current_url
    tw.get_current_url = lambda: ("https://new.trycloudflare.com", "cloudflared")
    try:
        r = tw.check_once(base, notify=lambda m: calls.append(m) or True)
    finally:
        tw.get_current_url = orig
    assert r["changed"] is True
    assert r["notified"] is True
    assert len(calls) == 1
    assert "https://new.trycloudflare.com" in calls[0]
    assert "painel mudou" in calls[0]
    # persistiu
    assert tw.load_last(base)["url"] == "https://new.trycloudflare.com"


def test_tunnel_down_silent_no_notify(tmp_path):
    base = str(tmp_path)
    calls = []
    orig = tw.get_current_url
    tw.get_current_url = lambda: (None, "none")
    try:
        r = tw.check_once(base, notify=lambda m: calls.append(m) or True)
    finally:
        tw.get_current_url = orig
    assert r["ok"] is False
    assert calls == []


def test_forbidden_port_alert(tmp_path):
    base = str(tmp_path)
    calls = []
    orig = tw.get_current_url
    tw.get_current_url = lambda: ("https://x.trycloudflare.com:8780", "cloudflared")
    try:
        r = tw.check_once(base, notify=lambda m: calls.append(m) or True)
    finally:
        tw.get_current_url = orig
    assert r["forbidden"] is True
    assert "ALERTA" in calls[0]


def test_separation_tunnel_only_dashboard():
    assert TUNNEL_TARGET_PORT == 8766
    assert SCHEDULER_PORT == 8780
    assert TUNNEL_TARGET_PORT not in TUNNEL_FORBIDDEN_PORTS
    assert SCHEDULER_PORT in TUNNEL_FORBIDDEN_PORTS
    assert ":8766" in tunnel_target()
    assert ":8780" not in tunnel_target()


def test_sched_proxy_targets_local_scheduler_only():
    import inspect
    from gateway import web
    src = inspect.getsource(web.GatewayHTTPHandler._sched_proxy)
    assert "127.0.0.1:8780" in src
    assert "8766" not in src


def test_dashboard_serves_no_public_scheduler_routes():
    import inspect
    from gateway import web
    get_src = inspect.getsource(web.GatewayHTTPHandler.do_GET)
    # Nenhuma rota de agendamento pública sem auth servida na 8766:
    assert "/api/chat" not in get_src
    assert "/api/appointment" not in get_src
    assert "chat.html" not in get_src or "dashboard" in get_src
