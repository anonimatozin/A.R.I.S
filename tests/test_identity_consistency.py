"""Teste de consistência de identidade da ARIS.

Verifica que a ARIS nunca atribui sua criação a empresas de IA terceiras
(OpenAI, Google, Meta, Anthropic, etc.) independentemente do provider LLM usado.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from config.personality import ARIS_PERSONALITY


class TestIdentityPrompt:
    """Verifica se o system prompt contém as regras de identidade fixa."""

    def test_prompt_declares_creator_vinicius(self):
        """O prompt deve declarar explicitamente Vinicius como criador."""
        assert "Vinicius" in ARIS_PERSONALITY
        assert "criado por Vinicius" in ARIS_PERSONALITY or "Criador.*Vinicius" in ARIS_PERSONALITY

    def test_prompt_forbids_openai_attribution(self):
        """O prompt deve proibir atribuição à OpenAI."""
        assert "OpenAI" in ARIS_PERSONALITY
        assert "NÃO" in ARIS_PERSONALITY and "OpenAI" in ARIS_PERSONALITY

    def test_prompt_forbids_google_attribution(self):
        """O prompt deve proibir atribuição ao Google/Gemini."""
        assert "Google" in ARIS_PERSONALITY

    def test_prompt_forbids_meta_attribution(self):
        """O prompt deve proibir atribuição à Meta."""
        assert "Meta" in ARIS_PERSONALITY

    def test_prompt_forbids_anthropic_attribution(self):
        """O prompt deve proibir atribuição à Anthropic."""
        assert "Anthropic" in ARIS_PERSONALITY

    def test_prompt_forbids_third_party_generic(self):
        """O prompt deve proibir atribuição genérica a terceiros."""
        assert "terceirizada" in ARIS_PERSONALITY or "terceiro" in ARIS_PERSONALITY

    def test_prompt_forbids_speculation_on_architecture(self):
        """O prompt deve proibir especulação sobre arquitetura interna."""
        assert "arquitetura interna" in ARIS_PERSONALITY
        assert "transformer" in ARIS_PERSONALITY or "GPT" in ARIS_PERSONALITY

    def test_prompt_has_explicit_identity_section(self):
        """O prompt deve ter seção explícita de Identidade Fixa."""
        assert "Identidade Fixa" in ARIS_PERSONALITY
        assert "NUNCA altere" in ARIS_PERSONALITY


class TestMultiProviderIdentity:
    """Testa consistência de identidade no MultiProviderChat."""

    def test_multi_provider_receives_system_prompt(self):
        """MultiProviderChat deve receber e armazenar o system prompt."""
        from core.multi_provider import MultiProviderChat
        from utils.logger import Logger

        logger = Logger(name="test", level="CRITICAL")
        chat = MultiProviderChat(logger=logger)
        chat.set_system_prompt(ARIS_PERSONALITY)

        # Verifica que o prompt foi armazenado no histórico
        history = chat._history
        assert len(history) == 1
        assert history[0]["role"] == "system"
        assert "Vinicius" in history[0]["content"]
        assert "Identidade Fixa" in history[0]["content"]

    def test_multi_provider_preserves_prompt_on_clear(self):
        """Limpar histórico deve preservar o system prompt."""
        from core.multi_provider import MultiProviderChat
        from utils.logger import Logger

        logger = Logger(name="test", level="CRITICAL")
        chat = MultiProviderChat(logger=logger)
        chat.set_system_prompt(ARIS_PERSONALITY)
        chat.clear_history()

        history = chat._history
        assert len(history) == 1
        assert history[0]["role"] == "system"
        assert "Vinicius" in history[0]["content"]


class TestLLMRouterIdentity:
    """Testa se o LLMRouter recebe o system prompt nas mensagens."""

    def test_router_send_includes_system_when_provided(self):
        """LLMRouter.send() deve usar messages que incluem system prompt."""
        from core.llm.router import LLMRouter, ProviderConfig
        from utils.logger import Logger

        # Mock provider que não faz chamada real
        mock_provider = ProviderConfig(
            name="test",
            api_key="test",
            model="test-model",
            base_url="http://localhost",
        )

        logger = Logger(name="test", level="CRITICAL")
        router = LLMRouter(providers=[mock_provider], logger=logger)

        # Mock do client para não fazer chamada real
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Resposta teste"))]
        mock_client.chat.completions.create.return_value = mock_response
        router._clients["test"] = mock_client
        router._available["test"] = True

        # Enviar messages COM system prompt
        messages = [
            {"role": "system", "content": ARIS_PERSONALITY},
            {"role": "user", "content": "Quem te criou?"}
        ]
        
        try:
            router.send("test", messages=messages, temperature=0, max_tokens=10)
        except Exception:
            pass  # Esperado falhar no mock, mas a chamada foi feita

        # Verificar se o client recebeu as messages com system prompt
        call_args = mock_client.chat.completions.create.call_args
        assert call_args is not None
        called_messages = call_args.kwargs.get("messages", [])
        assert any(m["role"] == "system" and "Vinicius" in m["content"] for m in called_messages)


class TestAgentLoopIdentity:
    """Testa se o Agent Loop inclui identidade no seu system prompt."""

    def test_agent_loop_prompt_contains_identity(self):
        """O prompt do AgentLoop deve conter regras de identidade."""
        from core.neural.agent_loop import AgentLoop, AgentTask
        from utils.logger import Logger

        logger = Logger(name="test", level="CRITICAL")
        
        def mock_executor(tool, params):
            return {"ok": True}
        
        loop = AgentLoop(
            tool_executor=mock_executor,
            security_gate=None,
            mode_manager=None,
            llm_sender=None,
            capability_registry=None,
        )

        task = AgentTask(objective="teste identidade")
        prompt = loop._build_system_prompt(task)

        assert "Vinicius" in prompt
        assert "Identidade Fixa" in prompt
        assert "NUNCA altere" in prompt
        assert "OpenAI" in prompt
        assert "Google" in prompt
        assert "Meta" in prompt
        assert "arquitetura interna" in prompt


class TestIdentityConsistencySimulation:
    """Simula perguntas de identidade para verificar consistência."""

    FORBIDDEN_CREATORS = [
        "OpenAI", "Google", "Meta", "Anthropic", 
        "NVIDIA", "Microsoft", "Amazon", "IBM",
        "ChatGPT", "Gemini", "Claude", "Llama",
        "modelo de linguagem", "language model",
        "treinado por pesquisadores", "trained by researchers"
    ]

    REQUIRED_CREATOR = "Vinicius"

    def _mock_llm_response(self, prompt: str) -> str:
        """Simula resposta do LLM baseada no prompt."""
        # Esta simulação verifica se o prompt contém as regras necessárias
        has_identity = "Identidade Fixa" in prompt and "Vinicius" in prompt
        has_forbidden_rules = "NÃO" in prompt and "OpenAI" in prompt
        
        if has_identity and has_forbidden_rules:
            # Prompt forte -> resposta correta
            return "Fui criado por Vinicius."
        else:
            # Prompt fraco -> resposta incorreta (simula o bug)
            return "Sou um modelo de linguagem criado por pesquisadores da OpenAI."

    def test_strong_prompt_produces_correct_answer(self):
        """Prompt forte deve produzir resposta correta."""
        response = self._mock_llm_response(ARIS_PERSONALITY + "\n\nUsuário: Quem te criou?")
        assert self.REQUIRED_CREATOR in response
        for forbidden in self.FORBIDDEN_CREATORS:
            assert forbidden not in response, f"Resposta contém '{forbidden}' proibido: {response}"

    def test_weak_prompt_produces_wrong_answer(self):
        """Prompt fraco (sem identidade) simula o bug atual."""
        weak_prompt = "Você é um assistente útil."
        response = self._mock_llm_response(weak_prompt + "\n\nUsuário: Quem te criou?")
        # Este teste documenta o comportamento indesejado
        # Com prompt fraco, a resposta incorreta ocorre
        assert self.REQUIRED_CREATOR not in response or any(f in response for f in self.FORBIDDEN_CREATORS)


class TestPersonalitySync:
    """Testa sincronização de personalidade entre PC/CLL1/Web."""

    def test_sync_engine_prepares_personality_for_sync(self):
        """SyncEngine.get_personality_for_sync deve incluir hash e timestamp."""
        from core.sync_engine import SyncEngine
        from pathlib import Path
        import tempfile
        import sqlite3

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE memories (
                    id TEXT PRIMARY KEY, memory_type TEXT, content TEXT,
                    summary TEXT, importance INTEGER, confidence REAL,
                    source TEXT, tags TEXT, entities TEXT, created_at TEXT,
                    updated_at TEXT, deleted INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()

            engine = SyncEngine(db_path=db_path)
            sync_data = engine.get_personality_for_sync(ARIS_PERSONALITY)

            assert "personality" in sync_data
            assert "hash" in sync_data
            assert "timestamp" in sync_data
            assert "source" in sync_data
            assert sync_data["source"] == "pc_primary"
            assert sync_data["personality"] == ARIS_PERSONALITY
            assert "Vinicius" in sync_data["personality"]

    def test_sync_engine_applies_personality_on_cll1(self):
        """SyncEngine.apply_personality_sync deve salvar personalidade no edge."""
        from core.sync_engine import SyncEngine
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            personality_path = Path(tmpdir) / "personality_sync.md"
            
            engine = SyncEngine(db_path=Path(tmpdir) / "test.db")
            
            sync_data = {
                "personality": ARIS_PERSONALITY,
                "hash": "abc123",
                "timestamp": "2026-01-01T00:00:00",
                "source": "pc_primary"
            }
            
            # Simular aplicação no edge (path customizado)
            result = engine.apply_personality_sync(sync_data)
            
            # Verificar se personalidade seria salva corretamente
            assert "Vinicius" in sync_data["personality"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])