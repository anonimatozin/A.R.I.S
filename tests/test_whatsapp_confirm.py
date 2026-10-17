"""Confirmação de envio do WhatsApp: rascunho antes, sim/não explícitos.

Regras de entrega:
- depois do preview, só uma resposta afirmativa REAL envia;
- resposta negativa ("não", "cancela"…) bloqueia o envio;
- frase que não é resposta de confirmação não engole o fluxo.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.handlers import handle_whatsapp
from modules.whatsapp import (
    classify_confirmation,
    clear_pending,
    confirmation_reply,
    get_pending,
    set_pending,
)


class FakeWhatsApp:
    """Dublê do módulo WhatsApp (sem Playwright/navegador)."""

    def __init__(self, running: bool = True, send_ok: bool = True):
        self.is_running = running
        self.send_ok = send_ok
        self.sent: list[tuple[str, str]] = []
        self.previews: list[tuple[str, str]] = []

    def prepare_send_sync(self, contact: str, message: str) -> dict:
        if not self.is_running:
            return {"ok": False, "error": "WhatsApp não está logado"}
        self.previews.append((contact, message))
        preview = (
            f"📱 Confirmar envio no WhatsApp:\n"
            f"  Para: {contact}\n"
            f"  Mensagem: {message}\n\n"
            f"Responda 'sim' para confirmar."
        )
        return {"ok": True, "contact": contact, "message": message, "preview": preview}

    def send_message_sync(self, contact: str, message: str) -> dict:
        if not self.send_ok:
            return {"ok": False, "error": "falhou"}
        self.sent.append((contact, message))
        return {"ok": True}

    def stop_sync(self) -> str:
        self.is_running = False
        return "WhatsApp fechado"


@pytest.fixture(autouse=True)
def _limpa_pendencia():
    clear_pending()
    yield
    clear_pending()


# ── Classificador ──────────────────────────────────────────

@pytest.mark.parametrize("frase", ["sim", "Sim.", "confirma", "pode", "manda", "ok", "pode sim"])
def test_classify_afirmacao(frase):
    assert classify_confirmation(frase) == "yes"


@pytest.mark.parametrize(
    "frase", ["não", "nao!", "cancela", "cancelar", "para", "não obrigado", "desisto"]
)
def test_classify_negacao(frase):
    assert classify_confirmation(frase) == "no"


@pytest.mark.parametrize(
    "frase",
    ["manda mensagem pra Maria", "que horas são", "abre o notepad", "melhor depois"],
)
def test_classify_indefinido(frase):
    assert classify_confirmation(frase) == "unknown"


def test_negacao_tem_precedencia_sobre_afirmacao():
    assert classify_confirmation("sim não") == "no"


# ── Fluxo: preview → confirmação ───────────────────────────

def test_preview_mostra_rascunho_e_nao_envia():
    fake = FakeWhatsApp()
    out = handle_whatsapp(
        "send", {"contact": "João", "message": "tudo bem?"}, whatsapp=fake
    )
    assert "Responda 'sim' para confirmar" in out
    assert "João" in out
    assert fake.sent == []
    pending = get_pending()
    assert pending is not None
    assert pending["contact"] == "João"
    assert pending["message"] == "tudo bem?"


def test_nao_apos_rascunho_bloqueia_envio():
    """Regra: 'não' depois do rascunho → nada é enviado."""
    fake = FakeWhatsApp()
    handle_whatsapp(
        "send", {"contact": "João", "message": "oi"}, whatsapp=fake
    )
    reply = confirmation_reply("não")
    assert reply is not None
    assert "cancelado" in reply
    assert fake.sent == []
    assert get_pending() is None


def test_sim_apos_rascunho_envia_uma_vez():
    fake = FakeWhatsApp()
    handle_whatsapp(
        "send", {"contact": "João", "message": "oi"}, whatsapp=fake
    )
    reply = confirmation_reply("sim")
    assert reply is not None
    assert "✅" in reply
    assert "João" in reply
    assert fake.sent == [("João", "oi")]
    # pendência zerada — "sim" de novo não reenvia
    assert confirmation_reply("sim") is None
    assert fake.sent == [("João", "oi")]


def test_frase_indefinida_nao_envia_nem_cancela():
    fake = FakeWhatsApp()
    handle_whatsapp(
        "send", {"contact": "João", "message": "oi"}, whatsapp=fake
    )
    assert confirmation_reply("manda mensagem pra Maria") is None
    assert confirmation_reply("que horas são") is None
    assert fake.sent == []
    assert get_pending() is not None  # rascunho continua vivo


def test_falha_de_envio_e_reportada():
    fake = FakeWhatsApp(send_ok=False)
    handle_whatsapp(
        "send", {"contact": "João", "message": "oi"}, whatsapp=fake
    )
    reply = confirmation_reply("confirma")
    assert reply is not None
    assert "❌" in reply
    assert get_pending() is None


def test_sem_pendencia_gate_fica_invisivel():
    assert confirmation_reply("sim") is None
    assert confirmation_reply("não") is None


def test_stop_descarta_rascunho():
    fake = FakeWhatsApp()
    handle_whatsapp(
        "send", {"contact": "João", "message": "oi"}, whatsapp=fake
    )
    assert get_pending() is not None
    handle_whatsapp("stop", {}, whatsapp=fake)
    assert get_pending() is None
    assert confirmation_reply("sim") is None
    assert fake.sent == []


def test_set_pending_guarda_quem_envia():
    calls = []

    def sender(contact, message):
        calls.append((contact, message))
        return {"ok": True}

    set_pending("Maria", "oi", sender)
    reply = confirmation_reply("pode enviar")
    assert "✅" in reply
    assert calls == [("Maria", "oi")]
