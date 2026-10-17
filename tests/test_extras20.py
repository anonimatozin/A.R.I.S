"""Testes das 20 funções novas (extras20) — sem rede, sem GPU."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.extras20 import (
    handle, focus_set, focus_clear, is_focus_active, self_check,
    checklist_create, check_duplicate_text, clipboard_search, changelog_natural,
    backup_integrity, security_log_today, privacy_set, privacy_is_on,
    voice_note_save, system_anomaly_check, contextual_style, memory_export,
    offline_status, approval_queue_text, weekly_summary, agent_audit_text,
    morning_briefing, is_quiet_hours,
)


def test_focus_roundtrip():
    assert "foco" in focus_set(1).lower()
    assert is_focus_active() is True
    focus_clear()
    assert is_focus_active() is False


def test_self_check_real():
    s = self_check()
    assert "memória" in s or "memoria" in s.lower()


def test_checklist_and_duplicate():
    r = checklist_create("lembra de levar carregador, caderno e crachá amanhã")
    assert "3 itens" in r or "carregador" in r
    dup = check_duplicate_text("levar carregador caderno crachá")
    assert dup is not None


def test_clipboard_search_empty():
    assert isinstance(clipboard_search("zzzqqq"), str)


def test_changelog():
    assert isinstance(changelog_natural(3), str)


def test_backup_integrity():
    assert isinstance(backup_integrity(), str)


def test_security_log():
    assert isinstance(security_log_today(), str)


def test_privacy():
    privacy_set(True)
    assert privacy_is_on() is True
    privacy_set(False)
    assert privacy_is_on() is False


def test_voice_note():
    assert "arquivada" in voice_note_save("ideia de teste").lower()


def test_anomaly_none_or_alert():
    assert system_anomaly_check() is None or isinstance(system_anomaly_check(), str)


def test_contextual_style():
    assert contextual_style() in ("conciso", "normal")


def test_offline_status():
    assert isinstance(offline_status(), str)


def test_approvals():
    assert isinstance(approval_queue_text(), str)


def test_weekly():
    assert isinstance(weekly_summary(), str)


def test_agent_audit():
    assert isinstance(agent_audit_text(3), str)


def test_morning():
    assert len(morning_briefing()) > 5


def test_quiet_hours_type():
    assert isinstance(is_quiet_hours(), bool)


def test_handle_router():
    assert handle("aris modo foco 1 hora") is not None
    focus_clear()
    assert handle("aris como você está") is not None
    assert handle("changelog") is not None
    assert handle("log de segurança de hoje") is not None
    assert handle("resumo semanal") is not None
    assert handle("fila de aprovações pendentes") is not None
    assert handle("modo apresentação") is not None
    privacy_set(False)
    assert handle("anotar ideia brilhante de teste") is not None
    assert handle("exportar memória para /tmp/aris_mem_test") is not None
    assert handle("modo offline") is not None
    assert handle("oi tudo bem?") is None  # não é extras20
