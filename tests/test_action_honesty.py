"""Testes de honestidade das ações (Fase 1).

Quando uma ferramenta FALHA, a resposta da A.R.I.S. não pode afirmar
sucesso. Cobrimos as duas camadas:

1. ActionEngine: uma resposta textual de falha (ex.: "Ação desconhecida:
   abrir") tem de ser classificada como falha, não sucesso.
2. Aris._execute_intent: a falha real precisa voltar para a fala (em vez
   de virar None e deixar a frase genérica do LLM afirmar sucesso).
"""

from types import SimpleNamespace

import pytest

from core.commands import CommandRegistry
from core.neural.actions.action_engine import ActionResult
from core.neural.decision.decision_engine import Decision

# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def failing_registry():
    """Registry cuja ferramenta devolve uma resposta textual de FALHA."""
    reg = CommandRegistry()

    @reg.register_intent("desktop", "controle do desktop")
    def _desktop(action, params, **ctx):
        return f"Ação desconhecida: {action}"

    return reg


@pytest.fixture
def ok_registry():
    reg = CommandRegistry()

    @reg.register_intent("desktop", "controle do desktop")
    def _desktop(action, params, **ctx):
        return "Abrindo firefox..."

    return reg


# ── 1. ActionEngine classifica falha como falha ─────────────

class TestActionEngineHonesty:
    def test_unknown_action_is_not_success(self, failing_registry):
        from core.neural.actions.action_engine import ActionEngine

        eng = ActionEngine(command_registry=failing_registry)
        result = eng.execute(Decision(module="desktop", action="abrir"))

        assert isinstance(result, ActionResult)
        # O defeito original: "Ação desconhecida: abrir" casava como sucesso.
        assert result.success is False
        assert "abrir" in result.output  # o motivo real é preservado

    def test_failure_is_counted_in_stats(self, failing_registry):
        from core.neural.actions.action_engine import ActionEngine

        eng = ActionEngine(command_registry=failing_registry)
        eng.execute(Decision(module="desktop", action="abrir"))

        stats = eng.get_stats()
        assert stats["failures"] >= 1

    def test_success_still_success(self, ok_registry):
        from core.neural.actions.action_engine import ActionEngine

        eng = ActionEngine(command_registry=ok_registry)
        result = eng.execute(Decision(module="desktop", action="open_app",
                                      parameters={"app": "firefox"}))

        assert result.success is True
        assert result.output == "Abrindo firefox..."


# ── 2. A resposta falável NÃO afirma sucesso ────────────────

class TestSpokenResponseHonesty:
    def _run_execute_intent(self, monkeypatch, tool_result: ActionResult):
        """Chama o código real de Aris._execute_intent com um self stub."""
        import core.aris as aris_mod

        # Registry real do módulo, mas com um intent "desktop" qualquer.
        reg = CommandRegistry()

        @reg.register_intent("desktop", "desktop")
        def _desktop(action, params, **ctx):
            return "nunca chamado diretamente"

        monkeypatch.setattr(aris_mod, "registry", reg)

        # Neural stub: decide() devolve a decisão; execute() devolve o
        # resultado da ferramenta que simulamos (falha ou sucesso).
        neural = SimpleNamespace(
            decision=SimpleNamespace(decide=lambda intent, source=None:
                                     Decision(module=intent.module,
                                              action=intent.action)),
            execute=lambda decision, ctx=None: tool_result,
        )

        stub = SimpleNamespace(
            _neural=neural,
            _build_handler_context=lambda origin=None: {},
        )

        intent = SimpleNamespace(module="desktop", action="abrir", params={})
        return aris_mod.Aris._execute_intent(stub, intent, origin=None)

    def test_failed_action_speaks_failure(self, monkeypatch):
        tool_result = ActionResult(
            success=False,
            output="Ação desconhecida: abrir",
            error="",
            module="desktop",
            action="abrir",
        )
        spoken = self._run_execute_intent(monkeypatch, tool_result)

        # A falha real volta para a resposta...
        assert spoken is not None
        assert "abrir" in spoken
        # ...e a resposta NÃO afirma sucesso.
        assert "Pronto" not in spoken
        assert "feitas" not in spoken.lower()
        assert spoken.lower().startswith("não deu certo")

    def test_successful_action_speaks_output(self, monkeypatch):
        tool_result = ActionResult(
            success=True,
            output="Abrindo firefox...",
            error="",
            module="desktop",
            action="open_app",
        )
        spoken = self._run_execute_intent(monkeypatch, tool_result)

        assert spoken == "Abrindo firefox..."
