"""Lista fixa de ações permitidas no bridge de controle do PC (:8770).

O ``pc_listener`` executa SOMENTE ações declaradas em ``ALLOWED_COMMANDS``.
O LLM / NLU escolhe uma ação da lista e envia parâmetros validados —
nunca código ou comando livre (o antigo ``exec`` de Python arbitrário foi
removido do bridge).

Regras:
- ``validate_body`` é a trava única usada pelo ``do_POST`` do listener.
- ``build_pc_payload`` é o construtor dos enviadores (planner executor);
  garante que só saiam payloads compatíveis com a lista.
- ``SCHEDULE_SNIPPETS`` são trechos fixos do próprio bridge (literais);
  valores variáveis entram apenas como ``sys.argv[1]``, nunca interpolados.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

__all__ = [
    "ALLOWED_COMMANDS",
    "PROJECT_ROOT",
    "SCHEDULE_SNIPPETS",
    "build_pc_payload",
    "validate_body",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Lista fixa ─────────────────────────────────────────────
# Adicionar uma ação aqui + handler no pc_listener é o ÚNICO caminho
# para o bridge executar algo. "exec" NÃO existe mais.

ALLOWED_COMMANDS = frozenset({
    # Energia / sessão
    "status",
    "shutdown",
    "restart",
    "lock",
    "sleep",
    # Abrir apps e URLs
    "open_app",
    "open_url",
    # Agendamento de energia (snippets fixos no bridge)
    "schedule_shutdown",
    "schedule_wake",
    "schedule_cancel",
    "schedule_query",
    # Automação de navegador (Playwright, sem shell)
    "browser_open",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "browser_snapshot",
    "browser_close",
    "browser_js",
})

# Trechos fixos executados pelo bridge via [sys.executable, "-c", snippet, at].
# O valor de "at" (se houver) é passado como sys.argv[1] — zero interpolação.
SCHEDULE_SNIPPETS: dict[str, str] = {
    "schedule_shutdown": (
        "import sys\n"
        "from core.tools.power_scheduler import schedule_shutdown\n"
        "print(schedule_shutdown(at=sys.argv[1]))\n"
    ),
    "schedule_wake": (
        "import sys\n"
        "from core.tools.power_scheduler import schedule_wake\n"
        "print(schedule_wake(at=sys.argv[1]))\n"
    ),
    "schedule_cancel": (
        "from core.tools.power_scheduler import cancel_shutdown\n"
        "print(cancel_shutdown())\n"
    ),
    "schedule_query": (
        "from core.tools.power_scheduler import get_scheduled_shutdown\n"
        "print(get_scheduled_shutdown())\n"
    ),
}

# ── Validadores ────────────────────────────────────────────

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_URL_RE = re.compile(r"^https?://[^\x00-\x1f\x7f\"']{1,2048}$", re.IGNORECASE)
# Metacaracteras de shell — proibidas no target de open_app (defesa em
# profundidade, mesmo sem shell: evita ambiguidade de parsing).
_APP_FORBIDDEN = set("\"'&|<>^`")


def _valid_at(value: str) -> bool:
    """Valida horário agendado: HH:MM ou YYYY-MM-DD HH:MM (intervalo real)."""
    from datetime import datetime

    for fmt in ("%H:%M", "%Y-%m-%d %H:%M"):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def _text_param(body: dict[str, Any], key: str, max_len: int) -> tuple[str, str | None]:
    """Valida um parâmetro texto obrigatório. Retorna (valor, erro)."""
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        return "", f"{key}: parâmetro ausente ou vazio"
    text = value.strip()
    if len(text) > max_len:
        return "", f"{key}: excede {max_len} caracteres"
    if _CONTROL_RE.search(text):
        return "", f"{key}: contém caracteres de controle"
    return text, None


def validate_body(body: Any) -> tuple[bool, str]:
    """Valida um payload do bridge contra a lista fixa de ações.

    Returns:
        (True, "") quando a ação e os parâmetros são permitidos;
        (False, motivo) quando fica de fora da lista / parâmetro inválido.
    """
    if not isinstance(body, dict):
        return False, "payload deve ser um objeto JSON"

    command = body.get("command")
    if not isinstance(command, str) or not command.strip():
        return False, "campo 'command' ausente"
    command = command.strip()

    if command not in ALLOWED_COMMANDS:
        return False, f"'{command}' não está na lista de ações permitidas"

    if command == "open_app":
        target, err = _text_param(body, "target", 512)
        if err:
            return False, err
        bad = _APP_FORBIDDEN.intersection(target)
        if bad:
            return False, f"target: caractere proibido {sorted(bad)!r}"
        return True, ""

    if command in ("open_url", "browser_navigate"):
        url, err = _text_param(body, "url", 2048)
        if err:
            return False, err
        if not _URL_RE.match(url):
            return False, "url: precisa começar com http:// ou https:// sem aspas"
        return True, ""

    if command == "browser_open":
        # url opcional — o handler aplica o default (google.com)
        url_opt = body.get("url")
        if url_opt is None or url_opt == "":
            return True, ""
        if not isinstance(url_opt, str) or not _URL_RE.match(url_opt.strip()):
            return False, "url: precisa começar com http:// ou https:// sem aspas"
        return True, ""

    if command in ("schedule_shutdown", "schedule_wake"):
        at, err = _text_param(body, "at", 32)
        if err:
            return False, err
        if not _valid_at(at):
            return False, "at: formato aceito é HH:MM ou YYYY-MM-DD HH:MM"
        return True, ""

    if command in ("schedule_cancel", "schedule_query"):
        return True, ""

    if command == "browser_click":
        _, err = _text_param(body, "selector", 1000)
        if err:
            return False, err
        return True, ""

    if command == "browser_type":
        _, err = _text_param(body, "selector", 1000)
        if err:
            return False, err
        value = body.get("text")
        if not isinstance(value, str) or not value.strip():
            return False, "text: parâmetro ausente ou vazio"
        if len(value) > 4000 or _CONTROL_RE.search(value):
            return False, "text: inválido (tamanho/caracteres)"
        return True, ""

    if command == "browser_js":
        script = body.get("script")
        if not isinstance(script, str) or not script.strip():
            return False, "script: parâmetro ausente ou vazio"
        if len(script) > 8000 or _CONTROL_RE.search(script):
            return False, "script: inválido (tamanho/caracteres)"
        return True, ""

    # Ações sem parâmetros: status, shutdown, restart, lock, sleep,
    # browser_screenshot, browser_snapshot, browser_close
    return True, ""


def build_pc_payload(
    action_type: str, parameters: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Mapeia uma ``ActionType`` do planner para payload da lista fixa.

    Retorna ``None`` quando a ação não tem equivalente na lista — nunca
    gera código livre. O payload final é revalidado por ``validate_body``.
    """
    params = parameters or {}

    simple = {
        "shutdown": {"command": "shutdown"},
        "restart": {"command": "restart"},
        "lock": {"command": "lock"},
        "sleep": {"command": "sleep"},
        "system_status": {"command": "status"},
        "cancel_schedule": {"command": "schedule_cancel"},
    }
    if action_type in simple:
        payload = simple[action_type]
    elif action_type == "open_app":
        target = params.get("app") or params.get("target") or ""
        if not isinstance(target, str) or not target.strip():
            return None
        payload = {"command": "open_app", "target": target.strip()}
    elif action_type == "open_url":
        url = params.get("url") or ""
        if not isinstance(url, str) or not url.strip():
            return None
        payload = {"command": "open_url", "url": url.strip()}
    elif action_type == "open_browser":
        url = params.get("url") or "https://www.google.com"
        payload = {"command": "open_url", "url": str(url).strip()}
    elif action_type == "search_web":
        query = params.get("query") or ""
        if not isinstance(query, str) or not query.strip():
            return None
        payload = {
            "command": "open_url",
            "url": f"https://www.google.com/search?q={quote(query.strip())}",
        }
    elif action_type in ("schedule_shutdown", "schedule_wake"):
        at = params.get("at") or params.get("time_str") or params.get("time") or ""
        if not isinstance(at, str) or not at.strip():
            return None
        payload = {"command": action_type, "at": at.strip()}
    else:
        # run_command, write_file, memory_* etc. — fora da lista.
        return None

    ok, _err = validate_body(payload)
    return payload if ok else None
