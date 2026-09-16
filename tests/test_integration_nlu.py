"""Testes da integracao NLU + Intelligence Tools (Fase 4)."""

import pytest
from core.advanced_interpreter import AdvancedInterpreter, Intent
from core.nlu import NLUEngine, IntentType


class TestNLUFastPath:
    """Testes do try_nlu_fast_path no AdvancedInterpreter."""

    def setup_method(self):
        self.interp = AdvancedInterpreter()

    def test_search_fast_path(self):
        """Pesquisa simples vai pro fast path."""
        r = self.interp.try_nlu_fast_path("pesquisa python programming")
        assert r is not None
        response, intents = r
        assert len(intents) == 1
        assert intents[0].module == "websearch"

    def test_weather_fast_path(self):
        """Tempo vai pro fast path."""
        r = self.interp.try_nlu_fast_path("tempo em sao paulo")
        assert r is not None
        response, intents = r
        assert intents[0].module == "weather"

    def test_verify_fast_path(self):
        """Verificacao vai pro fast path."""
        r = self.interp.try_nlu_fast_path("verifica se terra e redonda")
        assert r is not None
        response, intents = r
        assert intents[0].module == "intel_verify"

    def test_compare_fast_path(self):
        """Comparacao vai pro fast path."""
        r = self.interp.try_nlu_fast_path("compara python com javascript")
        assert r is not None
        response, intents = r
        assert intents[0].module == "intel_compare"

    def test_research_fast_path(self):
        """Pesquisa aprofundada vai pro fast path."""
        r = self.interp.try_nlu_fast_path("pesquisa aprofundada sobre IA")
        assert r is not None
        response, intents = r
        assert intents[0].module == "intel_research"

    def test_latest_fast_path(self):
        """Latest vai pro fast path."""
        r = self.interp.try_nlu_fast_path("ultima noticia sobre eleicoes")
        assert r is not None
        response, intents = r
        assert intents[0].module == "intel_latest"

    def test_explain_fast_path(self):
        """Explicacao vai pro fast path."""
        r = self.interp.try_nlu_fast_path("explica como funciona um processador")
        assert r is not None
        response, intents = r
        assert intents[0].module == "websearch"

    def test_conversation_returns_none(self):
        """Conversa retorna None (precisa de LLM)."""
        r = self.interp.try_nlu_fast_path("oi")
        assert r is None

    def test_unknown_returns_none(self):
        """Unknown retorna None."""
        r = self.interp.try_nlu_fast_path("asdfghjkl")
        assert r is None

    def test_nlu_confidence_used(self):
        """Confidence do NLU e usada no intent."""
        r = self.interp.try_nlu_fast_path("pesquisa sobre python")
        assert r is not None
        _, intents = r
        assert intents[0].confidence > 0.5

    def test_params_extracted(self):
        """Params sao extraidos corretamente."""
        r = self.interp.try_nlu_fast_path("tempo em rio de janeiro")
        assert r is not None
        _, intents = r
        assert "city" in intents[0].params

    def test_response_not_empty(self):
        """Resposta nao e vazia."""
        r = self.interp.try_nlu_fast_path("pesquisa teste")
        assert r is not None
        response, _ = r
        assert len(response) > 0


class TestNLUIntegration:
    """Testes de integracao NLU + sistema existente."""

    def setup_method(self):
        self.interp = AdvancedInterpreter()

    def test_nlu_lazy_load(self):
        """NLU e carregado sob demanda."""
        assert self.interp._nlu is None
        _ = self.interp.nlu
        assert self.interp._nlu is not None

    def test_nlu_returns_correct_type(self):
        """NLU retorna NLUEngine."""
        assert isinstance(self.interp.nlu, NLUEngine)

    def test_parse_ai_response_unchanged(self):
        """parse_ai_response continua funcionando."""
        response = 'Teste\n```json\n[{"module":"test","action":"exec","params":{},"confidence":0.9}]\n```'
        text, intents = self.interp.parse_ai_response(response)
        assert len(intents) == 1
        assert intents[0].module == "test"


class TestToolRegistryIntel:
    """Testes que intelligence tools aparecem no registry."""

    def test_registry_has_intel_tools(self):
        """Registry contem intelligence tools."""
        from core.tools.registry import get_tool_registry
        reg = get_tool_registry()
        tools = [t.name for t in reg.list_tools()]
        assert "intel_search" in tools
        assert "intel_research" in tools
        assert "intel_verify" in tools
        assert "intel_compare" in tools
        assert "intel_latest" in tools

    def test_executor_dispatches_intel(self):
        """Executor despacha intelligence tools."""
        from core.tools.executor import get_tool_executor
        executor = get_tool_executor()
        # Sem security gate, deve funcionar
        r = executor.execute("intel_search", {"query": "test"})
        assert r["ok"] is True
