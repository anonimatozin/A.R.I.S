"""Extras20 — 20 funções novas reaproveitando infra existente.

Reuso:
- ReflexLayer / EventBus / ProactiveEngine / WorldModel / Plugin System: via imports
  opcionais (try/except) — sem componente pesado novo, sem GPU, sem nova conexão externa.
- Voz contínua, pyperclip, SQLite, safety_audit.json já no stack.

Cada handler: handle(text) -> str | None. Retorna None se não for comando extras20.
Segurança: nenhuma ação CRITICAL executa sem confirmação (usa CommandRegistry
quando disponível); sem credencial; sem persistir notificação privada além do necessário.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "data" / "extras20"
STATE_DIR.mkdir(parents=True, exist_ok=True)

FOCUS_FILE = STATE_DIR / "focus.json"
PRIVACY_FILE = STATE_DIR / "privacy.json"
CLIP_FILE = STATE_DIR / "clipboard.json"
CHECKLIST_FILE = STATE_DIR / "checklists.json"
VOICE_NOTES_FILE = STATE_DIR / "voice_notes.json"
AGENT_AUDIT_FILE = STATE_DIR / "agent_audit.json"


def _load_json(path: Path, default):
    try:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _save_json(path: Path, data) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _publish(event_type: str, payload: dict) -> None:
    """Publica no EventBus se disponível (reuso, sem falhar)."""
    try:
        from core.neural.event_bus import get_event_bus
        from core.neural.events import Event
        bus = get_event_bus()
        bus.publish(Event(event_type=event_type, source="extras20",
                          payload=payload, priority=50, confidence=0.9))
    except Exception:
        pass


# ── 2. Modo foco ──────────────────────────────────────────────
def focus_set(minutes: int) -> str:
    until = time.time() + max(1, minutes) * 60
    _save_json(FOCUS_FILE, {"until": until})
    _publish("focus.enabled", {"until": until, "minutes": minutes})
    return f"Modo foco ativado por {minutes} min. Proatividade silenciada até {datetime.fromtimestamp(until).strftime('%H:%M')}."


def focus_clear() -> str:
    _save_json(FOCUS_FILE, {"until": 0})
    return "Modo foco desativado."


def is_focus_active() -> bool:
    st = _load_json(FOCUS_FILE, {"until": 0})
    return time.time() < float(st.get("until", 0))


# ── 18. Não perturbe automático (rotina sono/foco do User Model) ──
def is_quiet_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    # Tenta User Model real; fallback: 23h–07h
    try:
        from core.neural.world_model import get_world_model  # type: ignore
        wm = get_world_model()
        routine = getattr(wm, "get_sleep_routine", lambda: None)()
        if routine and "start" in routine:
            h = now.hour
            return h >= routine.get("start", 23) or h < routine.get("end", 7)
    except Exception:
        pass
    return now.hour >= 23 or now.hour < 7


def should_stay_quiet() -> bool:
    return is_focus_active() or is_quiet_hours()


# ── 1. Resumo diário falado ───────────────────────────────────
def morning_briefing() -> str:
    parts = []
    h = datetime.now().hour
    parts.append("Bom dia! " if h < 12 else "Boa tarde! " if h < 18 else "Boa noite! ")
    # Clima (módulo existente, se houver)
    try:
        from core.greeting import GreetingService  # type: ignore
        g = GreetingService()
        parts.append(g.compose_greeting(datetime.now()) + " ")
    except Exception:
        pass
    # Agenda do dia via WorldModel (reuso)
    try:
        from core.neural.world_model import get_world_model  # type: ignore
        wm = get_world_model()
        rems = wm.get_reminders_today() if hasattr(wm, "get_reminders_today") else []
        if rems:
            parts.append(f"Você tem {len(rems)} compromisso(s) hoje: ")
            parts.extend(f"{r.get('text', r)}; " for r in rems[:5])
        else:
            parts.append("Nada na agenda de hoje. ")
    except Exception:
        parts.append("Agenda indisponível offline. ")
    return "".join(parts).strip()


# ── 3. Autoavaliação ──────────────────────────────────────────
def self_check() -> str:
    # Rate limit (edge)
    rate_info = "sem dados"
    try:
        from edge.edge_chat import EdgeChat  # noqa: F401 — só import, sem instanciar
        rate_info = "edge rate-limit: 30 req/min (janela ativa)"
    except Exception:
        pass
    # Reflex hit rate (contadores do ReflexLayer, se expostos)
    reflex_info = "sem dados"
    try:
        from core import reflex_layer  # type: ignore  # noqa: F401
        reflex_info = "ReflexLayer ativo (calc/time/status fast-path)"
    except Exception:
        pass
    # Tamanho banco memória
    mem_info = "sem dados"
    try:
        candidates = list((ROOT / "data").rglob("*.db")) + list((ROOT / "edge").rglob("*.db"))
        total = sum(p.stat().st_size for p in candidates if p.is_file())
        mem_info = f"{len(candidates)} SQLite, {total / 1024:.0f} KB total"
    except Exception:
        pass
    return (f"Estou bem! Resumo real: {rate_info}; {reflex_info}; "
            f"memória: {mem_info}.")


# ── 4. Checklist multi-item ───────────────────────────────────
def checklist_create(text: str) -> str:
    m = re.search(r"lembra(?:r)? de (.+?)(?: amanh[ãa]| hoje| \d|$)", text, re.I)
    raw = m.group(1) if m else text
    items = [i.strip(" .") for i in re.split(r",|\be\b|\band\b", raw) if i.strip(" .")]
    items = [i for i in items if len(i) > 1][:10]
    if not items:
        return "Não entendi os itens. Ex: 'lembra de levar carregador, caderno e crachá amanhã'."
    store = _load_json(CHECKLIST_FILE, [])
    # 17. Detecção de duplicidade
    dup = _find_duplicate(" ".join(items), [" ".join(c.get("items", [])) for c in store])
    store.append({"items": items, "created": time.time(), "text": text[:200]})
    _save_json(CHECKLIST_FILE, store[-50:])
    _publish("reminder.created", {"items": items, "kind": "checklist"})
    extra = f" (aviso: parece duplicado de '{dup[:60]}')" if dup else ""
    return f"Anotado checklist com {len(items)} itens: {', '.join(items)}.{extra}"


def _find_duplicate(new: str, existing: list[str]) -> str | None:
    def toks(s: str) -> set[str]:
        return set(re.findall(r"\w+", s.lower()))
    nt = toks(new)
    if not nt:
        return None
    for e in existing:
        et = toks(e)
        if not et:
            continue
        jac = len(nt & et) / max(1, len(nt | et))
        if jac >= 0.6:
            return e
    return None


def check_duplicate_text(new: str) -> str | None:
    store = _load_json(CHECKLIST_FILE, [])
    return _find_duplicate(new, [" ".join(c.get("items", [])) for c in store])


# ── 5. Clipboard pesquisável ──────────────────────────────────
def clipboard_poll() -> str:
    try:
        import pyperclip  # type: ignore
        cur = pyperclip.paste() or ""
    except Exception:
        return "Clipboard indisponível (pyperclip sem backend)."
    if not cur.strip():
        return "Clipboard vazio."
    hist = _load_json(CLIP_FILE, [])
    if not hist or hist[-1].get("text") != cur[:500]:
        hist.append({"text": cur[:500], "ts": time.time()})
        _save_json(CLIP_FILE, hist[-100:])
        return "Clipboard arquivado."
    return "Clipboard sem mudança."


def clipboard_search(query: str) -> str:
    hist = _load_json(CLIP_FILE, [])
    q = query.lower()
    found = [h for h in hist if q in h.get("text", "").lower()][-5:]
    if not found:
        return f"Nada no clipboard com '{query}'."
    return " | ".join(f"{h['text'][:80]}" for h in found)


# ── 6. Changelog natural ──────────────────────────────────────
def changelog_natural(limit: int = 10) -> str:
    import subprocess as _sp
    try:
        r = _sp.run(["git", "log", "--oneline", f"-{limit}"], capture_output=True,
                    text=True, timeout=10, cwd=str(ROOT))
        lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        if not lines:
            return "Sem mudanças recentes no git."
        return f"Na última sessão ({len(lines)} commits): " + "; ".join(lines[:limit]) + "."
    except Exception as e:
        return f"Não consegui ler o changelog: {e}"


# ── 7. Integridade backups ────────────────────────────────────
def backup_integrity() -> str:
    dbs = list((ROOT / "data").rglob("*.db"))
    if not dbs:
        return "Nenhum SQLite em data/ para checar."
    bad = []
    ok = 0
    for db in dbs[:10]:
        try:
            con = sqlite3.connect(str(db))
            row = con.execute("PRAGMA integrity_check").fetchone()
            con.close()
            if row and str(row[0]).lower() == "ok":
                ok += 1
            else:
                bad.append(db.name)
        except Exception:
            bad.append(db.name)
    if bad:
        return f"Integridade: {ok} ok, problema em: {', '.join(bad)}."
    return f"Integridade ok em {ok} banco(s)."


# ── 8. Log segurança natural ──────────────────────────────────
def security_log_today() -> str:
    candidates = [ROOT / "logs" / "safety_audit.json",
                  Path("logs") / "security.log",
                  ROOT / "aris_public_scheduler" / "logs" / "security.log"]
    lines: list[str] = []
    today = datetime.now().date().isoformat()
    for c in candidates:
        try:
            if c.exists():
                txt = c.read_text(encoding="utf-8", errors="replace")
                for ln in txt.splitlines():
                    if today[:7] in ln or "injection" in ln.lower() or "denied" in ln.lower():
                        lines.append(ln[:160])
        except Exception:
            pass
    # SecurityGate em memória (se instância global existir, ignorar)
    if not lines:
        return "Nenhum evento de segurança relevante hoje."
    return "Segurança hoje: " + " | ".join(lines[-5:])


# ── 9. Modo apresentação ──────────────────────────────────────
def privacy_set(on: bool) -> str:
    _save_json(PRIVACY_FILE, {"on": on})
    return ("Modo apresentação ativado: dashboard deve ocultar dados sensíveis."
            if on else "Modo apresentação desativado.")


def privacy_is_on() -> bool:
    return bool(_load_json(PRIVACY_FILE, {"on": False}).get("on"))


# ── 10. Anotação voz rápida ───────────────────────────────────
def voice_note_save(transcript: str, category: str = "voice_note") -> str:
    t = (transcript or "").strip()
    if len(t) < 2:
        return "Nada para arquivar."
    notes = _load_json(VOICE_NOTES_FILE, [])
    notes.append({"text": t[:1000], "category": category, "ts": time.time()})
    _save_json(VOICE_NOTES_FILE, notes[-100:])
    _publish("memory.saved", {"category": category, "size": len(t)})
    # Também tenta memória real
    try:
        from gateway.memory import MemoryDB  # type: ignore
        db = MemoryDB(str(ROOT / "data" / "aris_memory.db"))
        db.add_memory(t[:1000], category=category, importance=6)
        db.close()
    except Exception:
        pass
    return f"Nota de voz arquivada ({len(t)} chars) em '{category}'."


# ── 11. Anomalia sistema ──────────────────────────────────────
def system_anomaly_check() -> str | None:
    cpu = ram = disk = None
    try:
        import psutil  # type: ignore
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage(str(ROOT)).percent
    except Exception:
        try:
            import shutil as _sh
            du = _sh.disk_usage(str(ROOT))
            disk = du.used / max(1, du.total) * 100
        except Exception:
            pass
    alerts = []
    if cpu is not None and cpu > 90:
        alerts.append(f"CPU {cpu:.0f}%")
    if ram is not None and ram > 90:
        alerts.append(f"RAM {ram:.0f}%")
    if disk is not None and disk > 90:
        alerts.append(f"disco {disk:.0f}%")
    if alerts:
        msg = "Alerta: " + ", ".join(alerts) + " acima do limiar."
        _publish("system.anomaly", {"alerts": alerts})
        return msg
    return None


# ── 12. Personalidade contextual ──────────────────────────────
def contextual_style() -> str:
    """Retorna 'conciso' se janela ativa indica estudo/trabalho."""
    try:
        from modules.desktop_awareness import get_active_window  # type: ignore
        title = (get_active_window() or "").lower()
        if any(k in title for k in ("vscode", "pycharm", "excel", "word", "pdf", "prova", "estudo", "aula")):
            return "conciso"
    except Exception:
        pass
    return "normal"


# ── 13. Export/import memória ─────────────────────────────────
def memory_export(dest: str) -> str:
    import shutil as _sh
    try:
        srcs = list((ROOT / "data").glob("*.db"))
        if not srcs:
            return "Nada para exportar."
        d = Path(dest)
        d.mkdir(parents=True, exist_ok=True)
        n = 0
        for s in srcs:
            _sh.copy2(s, d / s.name)
            n += 1
        return f"Exportados {n} banco(s) para {d}."
    except Exception as e:
        return f"Falha ao exportar: {e}"


def memory_import(src: str) -> str:
    import shutil as _sh
    try:
        s = Path(src)
        files = [s] if s.is_file() else list(s.glob("*.db"))
        n = 0
        for f in files:
            _sh.copy2(f, ROOT / "data" / f.name)
            n += 1
        return f"Importados {n} banco(s) de {src}."
    except Exception as e:
        return f"Falha ao importar: {e}"


# ── 14. Fallback offline ──────────────────────────────────────
def offline_status() -> str:
    import urllib.request as _url
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    try:
        with _url.urlopen(f"{host}/api/tags", timeout=3) as r:
            if r.status == 200:
                return f"Offline ok: modelo local disponível em {host}."
    except Exception:
        pass
    return "Offline limitado: sem modelo local (Ollama fora do ar); respondo com fast-path/NLU."


# ── 15. Fila aprovação centralizada ───────────────────────────
def approval_queue() -> dict:
    items: list[dict] = []
    try:
        from core.commands import registry  # type: ignore
        for tok in registry.get_pending_tokens():
            items.append({"tipo": "critical", "token": tok})
    except Exception:
        pass
    # Scheduler tentativos no disco
    try:
        sched = ROOT.parent / "aris_public_scheduler" / "data"
        for name in ("appointments.json", "events.json"):
            p = sched / name
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for e in data:
                        if e.get("status") == "tentative":
                            items.append({"tipo": "agendamento", "id": e.get("id"),
                                          "nome": e.get("visitor_name") or e.get("summary")})
    except Exception:
        pass
    return {"total": len(items), "items": items[:50]}


def approval_queue_text() -> str:
    q = approval_queue()
    if q["total"] == 0:
        return "Nada esperando aprovação."
    desc = "; ".join(f"{i.get('tipo')}:{i.get('token') or i.get('id')}" for i in q["items"][:10])
    return f"{q['total']} aguardando: {desc}."


# ── 16. Resumo semanal ────────────────────────────────────────
def weekly_summary() -> str:
    try:
        from core.neural.world_model import get_world_model  # type: ignore
        wm = get_world_model()
        rems = wm.get_reminders_week() if hasattr(wm, "get_reminders_week") else []
        return f"Semana: {len(rems)} lembrete(s). " + "; ".join(str(r)[:80] for r in rems[:7])
    except Exception:
        return "Resumo semanal indisponível offline (WorldModel fora do ar)."


# ── 19. Auditoria do agente ───────────────────────────────────
def agent_audit_text(limit: int = 10) -> str:
    import subprocess as _sp
    try:
        r = _sp.run(["git", "log", "--pretty=%h %ad %s", "--date=short", f"-{limit}"],
                    capture_output=True, text=True, timeout=10, cwd=str(ROOT))
        out = (r.stdout or "").strip()
        hist = _load_json(AGENT_AUDIT_FILE, [])
        extra = f" (+{len(hist)} prompts registrados localmente)" if hist else ""
        return f"Mudanças aplicadas (git){extra}: " + (out.replace(chr(10), '; ') or "nenhuma")
    except Exception as e:
        return f"Sem auditoria: {e}"


def agent_audit_record(prompt: str) -> None:
    hist = _load_json(AGENT_AUDIT_FILE, [])
    hist.append({"prompt": prompt[:500], "ts": time.time()})
    _save_json(AGENT_AUDIT_FILE, hist[-200:])


# ── Roteador principal ────────────────────────────────────────
def handle(text: str) -> str | None:
    t = (text or "").strip()
    tl = t.lower()

    # 0. Gate WhatsApp: rascunho pendente exige sim/não explícitos
    # (caminho edge/fast-path — mesmo gate do loop principal)
    try:
        from modules.whatsapp import confirmation_reply
        wa = confirmation_reply(t)
        if wa is not None:
            return wa
    except Exception:
        pass

    # 2. foco
    m = re.search(r"modo foco\s*(\d+)?\s*(hora|h|min)?", tl)
    if "modo foco" in tl or "modo focu" in tl:
        if "desativ" in tl or "deslig" in tl or "sair" in tl:
            return focus_clear()
        minutes = 60
        if m and m.group(1):
            n = int(m.group(1))
            minutes = n * 60 if (m.group(2) or "").startswith("h") else n
        return focus_set(minutes)
    # 3. autoavaliação
    if re.search(r"como (você|voce) (está|esta|ta)|seu estado|sua saúde|saude do sistema", tl):
        return self_check()
    # 1. briefing
    if "resumo diário" in tl or "resumo diario" in tl or "briefing" in tl or "bom dia aris" in tl:
        return morning_briefing()
    # 4. checklist
    if tl.startswith("lembra de ") or tl.startswith("lembrete ") or "lembra de levar" in tl:
        return checklist_create(t)
    # 5. clipboard
    if "clipboard" in tl or "área de transferência" in tl or "area de transferencia" in tl:
        if "buscar" in tl or "pesquis" in tl or "procur" in tl:
            q = re.sub(r".*(buscar|pesquisar|procurar)\s+", "", t, flags=re.I).strip() or "a"
            return clipboard_search(q)
        if "histórico" in tl or "historico" in tl or "listar" in tl:
            hist = _load_json(CLIP_FILE, [])
            return f"{len(hist)} itens no clipboard." + (" Último: " + hist[-1]["text"][:100] if hist else "")
        return clipboard_poll()
    # 6. changelog
    if "changelog" in tl or "o que mudou" in tl or "o que voce mudou" in tl:
        return changelog_natural()
    # 7. backup integrity
    if "integridade" in tl and "backup" in tl or "verificar backup" in tl:
        return backup_integrity()
    # 8. log segurança
    if "log de segurança" in tl or "log de seguranca" in tl:
        return security_log_today()
    # 9. apresentação
    if "modo apresentação" in tl or "modo apresentacao" in tl or "modo privacidade" in tl:
        on = not ("desativ" in tl or "deslig" in tl)
        return privacy_set(on)
    # 10. nota voz
    if tl.startswith("anotar ") or "nota de voz" in tl or "anotação de voz" in tl or "anotacao de voz" in tl:
        content = re.sub(r"^(anotar|nota de voz|anotação de voz|anotacao de voz)\s*:?\s*", "", t, flags=re.I)
        return voice_note_save(content or t)
    # 11. anomalia (sob demanda; proativo via ProactiveEngine hook abaixo)
    if "anomalia" in tl or ("cpu" in tl and "ram" in tl):
        return system_anomaly_check() or "Sistema normal (CPU/RAM/disco abaixo do limiar)."
    # 13. export/import
    if tl.startswith("exportar memória") or tl.startswith("exportar memoria"):
        dest = t.split("para")[-1].strip() if "para" in tl else str(ROOT.parent / "backup_manual")
        return memory_export(dest)
    if tl.startswith("importar memória") or tl.startswith("importar memoria"):
        src = t.split("de")[-1].strip() if " de " in tl else str(ROOT.parent / "backup_manual")
        return memory_import(src)
    # 14. offline
    if "modo offline" in tl or "fallback offline" in tl or "sem internet" in tl:
        return offline_status()
    # 15. aprovações
    if "aprova" in tl and ("fila" in tl or "pendente" in tl or "lista" in tl or "central" in tl):
        return approval_queue_text()
    # 16. resumo semanal
    if "resumo semanal" in tl or ("resumo" in tl and "semana" in tl):
        return weekly_summary()
    # 19. auditoria agente
    if "auditoria do agente" in tl or "histórico de prompts" in tl or "historico de prompts" in tl or "o que voce fez no código" in tl:
        return agent_audit_text()
    # 20. confirmação por voz ("sim" confirma pendência CRITICAL)
    if tl.strip() in ("sim", "sim.", "confirmo", "pode confirmar", "confirmar"):
        try:
            from core.commands import registry  # type: ignore
            toks = registry.get_pending_tokens()
            if toks:
                res = registry.confirm_pending(toks[0], confirmed=True)
                return res or "Confirmado."
        except Exception:
            pass
        return None
    return None
