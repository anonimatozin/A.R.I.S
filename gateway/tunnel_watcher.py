"""Tunnel Watcher — rede de segurança contra troca de endereço do painel.

Consulta periodicamente (default 60s):
  1. API local do ngrok (http://127.0.0.1:4040/api/tunnels), se ngrok em uso;
  2. Log do cloudflared (tunnel_live.err), formato quick Tunnel atual.

Persiste a última URL em data/last_tunnel_url.json. Se mudar, envia DM/
mensagem no Discord reaproveitando o mecanismo já aprovado (webhook, com
fallback pra DM via Bot REST API — mesmo padrão de
aris_public_scheduler/cll1_main.py; nenhuma permissão/escopo novo).

Sem spam: túnel fora do ar = retry silencioso (só debug). Notifica APENAS
na troca real de URL. Guarda de separação: se a URL apontar pra porta
proibida (ex: 8780 do scheduler), a mensagem sai como ALERTA.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Callable

logger = logging.getLogger("tunnel_watcher")

try:
    from gateway.tunnel_config import TUNNEL_FORBIDDEN_PORTS
except ImportError:  # rodando fora do pacote
    TUNNEL_FORBIDDEN_PORTS = frozenset({8780, 8765, 8770})

NGROK_API = "http://127.0.0.1:4040/api/tunnels"
CLOUDFLARED_LOG = Path(
    os.getenv(
        "TUNNEL_LOG_PATH",
        r"C:\Users\ADMINI~1\AppData\Local\Temp\opencode\tunnel_live.err",
    )
)
CLOUDFLARED_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)
GENERIC_URL_RE = re.compile(r"https://[a-z0-9.\-]+\.[a-z]{2,}(?::\d+)?(?:/\S*)?", re.I)

STATE_FILENAME = "last_tunnel_url.json"
CHECK_INTERVAL_S = int(os.getenv("TUNNEL_WATCH_INTERVAL", "60"))


def _repo_data_dir(base_dir: str | None = None) -> Path:
    if base_dir:
        return Path(base_dir) / "data"
    here = Path(__file__).resolve()
    # gateway/tunnel_watcher.py -> ARIS/
    root = here.parent.parent
    return root / "data"


def state_path(base_dir: str | None = None) -> Path:
    return _repo_data_dir(base_dir) / STATE_FILENAME


# ── Fontes de URL ─────────────────────────────────────────────

def get_ngrok_url(timeout: float = 5) -> str | None:
    """URL pública via API local do ngrok. None se ngrok fora do ar."""
    try:
        req = urllib.request.Request(NGROK_API, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        for t in body.get("tunnels", []):
            url = t.get("public_url", "")
            if url.startswith("https://"):
                return url
            if url.startswith("http://"):
                return url
    except Exception as e:
        logger.debug(f"ngrok API indisponível: {e}")
    return None


def get_cloudflared_url(log_path: Path | None = None) -> str | None:
    """Última URL quick Tunnel no log do cloudflared. None se ausente."""
    path = log_path or CLOUDFLARED_LOG
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"log cloudflared ilegível ({path}): {e}")
        return None
    found = CLOUDFLARED_RE.findall(text)
    return found[-1] if found else None


def get_current_url() -> tuple[str | None, str]:
    """Retorna (url, fonte). Fonte: 'ngrok' | 'cloudflared' | 'none'."""
    url = get_ngrok_url()
    if url:
        return url, "ngrok"
    url = get_cloudflared_url()
    if url:
        return url, "cloudflared"
    return None, "none"


# ── Estado ────────────────────────────────────────────────────

def load_last(base_dir: str | None = None) -> dict:
    try:
        p = state_path(base_dir)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"estado ilegível: {e}")
    return {}


def save_last(url: str, source: str, base_dir: str | None = None) -> None:
    p = state_path(base_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {"url": url, "source": source, "updated_at": time.time()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"falha ao persistir URL do túnel: {e}")


# ── Discord (webhook primeiro, DM do bot como fallback) ───────
# Mesmo padrão de aris_public_scheduler/cll1_main.py — sem escopo novo.

def _owner_id() -> str:
    for key in ("DISCORD_OWNER_ID", "DISCORD_ALLOWED_USER_ID"):
        val = (os.getenv(key, "") or "").strip()
        if val and val.isdigit():
            return val
    csv = os.getenv("DISCORD_ALLOWED_USERS", "") or ""
    for part in csv.split(","):
        part = part.strip()
        if part.isdigit():
            return part
    return ""


def _post_json(url: str, payload: dict, headers: dict) -> tuple[int, dict]:
    """POST JSON via urllib. Retorna (status, corpo)."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        try:
            body = json.loads(resp.read().decode("utf-8") or "{}")
        except Exception:
            body = {}
        return resp.status, body


def notify_discord(message: str) -> bool:
    """Envia mensagem: webhook se configurado, senão DM do bot (REST)."""
    webhook = (os.getenv("DISCORD_WEBHOOK_URL", "") or "").strip()
    if webhook:
        try:
            status, _ = _post_json(webhook, {"content": message[:1900]},
                                   {"Content-Type": "application/json"})
            return status in (200, 201, 204)
        except Exception as e:
            logger.warning(f"Discord webhook falhou: {e}")
            return False

    token = (os.getenv("DISCORD_BOT_TOKEN", "") or "").strip()
    owner = _owner_id()
    if not token or not owner:
        logger.warning("sem webhook nem bot/owner — notificação descartada")
        return False
    try:
        headers = {"Authorization": "Bot " + token,
                   "Content-Type": "application/json",
                   "User-Agent": "ARIS-TunnelWatcher/1.0"}
        status, channel = _post_json("https://discord.com/api/v10/users/@me/channels",
                                     {"recipient_id": owner}, headers)
        channel_id = channel.get("id", "")
        if status not in (200, 201) or not channel_id:
            return False
        status, _ = _post_json(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            {"content": message[:1900]}, headers)
        return status in (200, 201)
    except Exception as e:
        logger.warning(f"Discord DM falhou: {e}")
        return False


# ── Checagem ──────────────────────────────────────────────────

def check_once(
    base_dir: str | None = None,
    notify: Callable[[str], bool] | None = None,
) -> dict:
    """Uma passada: compara URL atual com a última. Retorna diagnóstico."""
    current, source = get_current_url()
    if not current:
        # Túnel ainda não subiu — retry silencioso, sem spammar erro.
        return {"ok": False, "changed": False, "reason": "tunnel_down"}

    last = load_last(base_dir)
    previous = last.get("url", "")
    if previous == current:
        return {"ok": True, "changed": False, "url": current, "source": source}

    m = re.search(r":(\d+)", current)
    forbidden = bool(m and int(m.group(1)) in TUNNEL_FORBIDDEN_PORTS)
    if forbidden:
        message = (f"⚠️ ALERTA: o túnel parece apontar pra porta proibida "
                   f"({m.group(1)} — scheduler/local, nunca expor): {current}")
    else:
        message = f"Endereço do painel mudou: {current}"
    sender = notify or notify_discord
    try:
        sent = bool(sender(message))
    except Exception as e:
        logger.warning(f"notify falhou: {e}")
        sent = False
    save_last(current, source, base_dir)
    return {"ok": True, "changed": True, "url": current, "source": source,
            "notified": sent, "forbidden": forbidden}


def run_loop(base_dir: str | None = None, interval: int = CHECK_INTERVAL_S) -> None:
    """Loop do watcher (processo leve)."""
    logging.basicConfig(level=logging.INFO)
    logger.info(f"tunnel watcher: intervalo {interval}s")
    while True:
        try:
            result = check_once(base_dir)
            if result.get("changed"):
                logger.info(f"túnel mudou → {result.get('url')} "
                            f"(notificado={result.get('notified')})")
        except Exception as e:
            logger.debug(f"watcher erro (retry silencioso): {e}")
        time.sleep(max(10, interval))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Watcher da URL pública do painel")
    parser.add_argument("--once", action="store_true", help="uma checagem e sai")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL_S)
    args = parser.parse_args()
    if args.once:
        print(json.dumps(check_once(), ensure_ascii=False, indent=2))
    else:
        run_loop(interval=args.interval)
