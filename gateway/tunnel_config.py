"""Tunnel config — fonte única da separação dashboard (cloud) x scheduler (local).

- Dashboard administrativo (porta 8766): ÚNICO serviço que pode ser exposto
  via túnel (cloudflared/ngrok). Rotas: /api/exec, /api/file, /api/users,
  /api/backup, WebSocket /api/ws/events + pontes admin do scheduler
  (/api/scheduler/*, todas exigindo auth + permissão).
- Site de agendamento público (porta 8780): processo FastAPI separado,
  bind em host/porta configuráveis abaixo. NUNCA entra no comando do túnel.
  Acesso: só rede local/LAN. Expor pra internet no futuro = decisão separada.

O watcher (gateway/tunnel_watcher.py) usa TUNNEL_TARGET_PORT como guarda:
se a URL pública detectar forwarding de outra porta, ele avisa no Discord
com alerta em vez de anunciar como endereço do painel.
"""

from __future__ import annotations

import os

# ── Dashboard (cloud) ─────────────────────────────────────────
TUNNEL_TARGET_HOST = os.getenv("ARIS_DASHBOARD_HOST", "192.168.0.106")
TUNNEL_TARGET_PORT = int(os.getenv("ARIS_DASHBOARD_PORT", "8766"))

# ── Scheduler público (local/LAN, nunca no túnel) ─────────────
SCHEDULER_HOST = os.getenv("SCHEDULER_HOST", "0.0.0.0")
SCHEDULER_PORT = int(os.getenv("SCHEDULER_PORT", os.getenv("ARIS_SCHEDULER_PORT", "8780")))

# Portas que o túnel NUNCA deve encaminhar (scheduler e outras locais)
TUNNEL_FORBIDDEN_PORTS = frozenset({SCHEDULER_PORT, 8765, 8770})


def tunnel_target() -> str:
    """URL local que o túnel deve encaminhar (dashboard)."""
    return f"http://{TUNNEL_TARGET_HOST}:{TUNNEL_TARGET_PORT}"


def is_forbidden_port(port: int) -> bool:
    return port in TUNNEL_FORBIDDEN_PORTS
