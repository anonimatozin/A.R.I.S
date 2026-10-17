"""Regressão: loop principal não pode ficar travado no ``input()``.

Bug real medido em execução ao vivo: o prompt usava ``input()`` puro —
o loop principal ficava BLOQUEADO no terminal e os comandos de voz
(wake word, enfileirados via ``send_message``) só eram processados
quando o usuário apertava Enter (no teste: resposta 98s depois, no
instante em que o stdin liberou). O EOF (Ctrl+D/pipe fechado) também
hot-spinhava prompts vazios infinitos no console.

Correção: leitora do terminal em thread + ``_terminal_queue`` com
timeout de 0,3s — a fila de voz é drenada sem depender do Enter.
"""

from __future__ import annotations

import queue
import time
from types import SimpleNamespace

from core.aris import Aris
from core.message_origin import MessageOrigin
from utils.terminal import ArisUI


class _Stub:
    """Stub mínimo com os atributos lidos por ``_get_input``."""

    def __init__(self) -> None:
        self._input_queue: queue.Queue = queue.Queue()
        self._terminal_queue: queue.Queue = queue.Queue()
        self._terminal_reader = None
        self._mic_mode = False
        self._hybrid_voice = SimpleNamespace(_recognizer=None, enabled=False)
        self._voice = None
        self._settings = SimpleNamespace(VERSION="1.0.0")
        self._llm_router = SimpleNamespace(provider_names=["groq"])
        self._memory = SimpleNamespace(get_stats=lambda: {})
        self._scheduler = SimpleNamespace(get_pending_count=lambda: 0)
        # Liga os métodos reais que _get_input invoca via self
        self._ensure_terminal_reader = Aris._ensure_terminal_reader.__get__(self)
        self._terminal_read_loop = Aris._terminal_read_loop.__get__(self)


def _block_terminal(**_kwargs):
    """Simula o usuário PARADO no prompt (input bloqueante)."""
    time.sleep(60)
    return ""


def test_voice_transcript_processed_without_terminal_enter(monkeypatch):
    """Cenário-chave: voz chega com o prompt travado → resposta em ≤1s."""
    monkeypatch.setattr(ArisUI, "input_modern", _block_terminal)
    stub = _Stub()
    Aris._get_input(stub)  # inicia a leitora (fica travada no "prompt")

    stub._input_queue.put(
        ("aris, tudo bem", MessageOrigin(source="voice", channel="mic", user_id="local"))
    )
    t0 = time.monotonic()
    text, origin = Aris._get_input(stub)
    elapsed = time.monotonic() - t0

    assert text == "aris, tudo bem"
    assert origin.source == "voice"
    assert elapsed < 1.0, f"voz demorou {elapsed:.1f}s com o prompt travado"


def test_get_input_returns_promptly_when_terminal_blocked(monkeypatch):
    """Sem entrada, _get_input devolve vazio em ~0,3s (não trava)."""
    monkeypatch.setattr(ArisUI, "input_modern", _block_terminal)
    stub = _Stub()

    t0 = time.monotonic()
    text, _origin = Aris._get_input(stub)
    elapsed = time.monotonic() - t0

    assert text == ""
    assert elapsed < 2.0, f"_get_input bloqueou {elapsed:.1f}s no terminal"


def test_typed_text_still_flows_via_reader(monkeypatch):
    """O texto digitado no terminal continua chegando ao loop principal."""
    calls = {"n": 0}

    def fake_input(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return "ola aris"
        time.sleep(30)
        return ""

    monkeypatch.setattr(ArisUI, "input_modern", fake_input)
    stub = _Stub()

    text = ""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not text:
        text, _origin = Aris._get_input(stub)
        if not text:
            time.sleep(0.05)

    assert text == "ola aris"


def test_eof_does_not_hot_spin(monkeypatch):
    """EOF eterno (Ctrl+D/pipe) não pode encher a fila com spam."""
    monkeypatch.setattr(ArisUI, "input_modern", lambda **_kwargs: "")
    stub = _Stub()
    Aris._get_input(stub)  # inicia a leitora
    time.sleep(1.2)
    assert stub._terminal_queue.empty(), (
        "EOF encheu a fila da leitora (hot-spin de prompts)"
    )
