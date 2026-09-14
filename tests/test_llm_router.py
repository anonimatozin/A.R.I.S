"""Tests for core.llm.router — LLMRouter, ProviderConfig, env parsing."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from core.llm.router import (
    AllProvidersFailedError,
    LLMRouter,
    ProviderConfig,
    parse_providers_from_env,
)


# ── ProviderConfig ──────────────────────────────────────────


class TestProviderConfig:
    def test_supports_text(self):
        cfg = ProviderConfig(name="a", api_key="k", model="m", capabilities=("text",))
        assert cfg.supports_text is True
        assert cfg.supports_vision is False

    def test_supports_vision(self):
        cfg = ProviderConfig(name="a", api_key="k", model="m", capabilities=("text", "vision"))
        assert cfg.supports_vision is True
        assert cfg.supports_text is True

    def test_empty_capabilities(self):
        cfg = ProviderConfig(name="a", api_key="k", model="m", capabilities=())
        assert cfg.supports_text is False
        assert cfg.supports_vision is False

    def test_default_capabilities_include_text(self):
        cfg = ProviderConfig(name="a", api_key="k", model="m")
        assert cfg.supports_text is True
        assert cfg.supports_vision is False


# ── parse_providers_from_env ─────────────────────────────────


class TestParseProviders:
    def test_auto_detect_groq(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        providers = parse_providers_from_env()
        names = [p.name for p in providers]
        assert "groq" in names
        assert "ollama" in names

    def test_auto_detect_gemini(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "gem_test")
        providers = parse_providers_from_env()
        names = [p.name for p in providers]
        assert "gemini" in names
        assert "ollama" in names

    def test_numbered_provider(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("ARIS_LLM_1_NAME", "openai")
        monkeypatch.setenv("ARIS_LLM_1_API_KEY", "sk-test")
        monkeypatch.setenv("ARIS_LLM_1_MODEL", "gpt-4o")
        monkeypatch.setenv("ARIS_LLM_1_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("ARIS_LLM_1_CAPABILITIES", "text,vision")
        providers = parse_providers_from_env()
        names = [p.name for p in providers]
        assert "openai" in names
        openai_p = next(p for p in providers if p.name == "openai")
        assert openai_p.model == "gpt-4o"
        assert openai_p.capabilities == ("text", "vision")
        assert "https://api.openai.com/v1" in openai_p.base_url

    def test_numbered_skips_incomplete(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("ARIS_LLM_2_NAME", "partial")
        monkeypatch.setenv("ARIS_LLM_2_API_KEY", "key-only")
        # Missing MODEL
        providers = parse_providers_from_env()
        names = [p.name for p in providers]
        assert "partial" not in names

    def test_numbered_skips_duplicate_name(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        monkeypatch.setenv("ARIS_LLM_1_NAME", "groq")
        monkeypatch.setenv("ARIS_LLM_1_API_KEY", "key")
        monkeypatch.setenv("ARIS_LLM_1_MODEL", "model")
        providers = parse_providers_from_env()
        groq_count = sum(1 for p in providers if p.name == "groq")
        assert groq_count == 1

    def test_ollama_always_present(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        providers = parse_providers_from_env()
        names = [p.name for p in providers]
        assert "ollama" in names

    def test_groq_model_from_aris_chat_model(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        monkeypatch.setenv("ARIS_CHAT_MODEL", "custom-model")
        providers = parse_providers_from_env()
        groq = next(p for p in providers if p.name == "groq")
        assert groq.model == "custom-model"

    def test_gemini_model_from_gemini_model(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gem_test")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
        providers = parse_providers_from_env()
        gemini = next(p for p in providers if p.name == "gemini")
        assert gemini.model == "gemini-2.5-pro"


# ── LLMRouter ───────────────────────────────────────────────


class TestLLMRouter:
    def _make_router(self, providers=None):
        if providers is None:
            providers = [
                ProviderConfig(name="groq", api_key="key", model="m", capabilities=("text",)),
            ]
        return LLMRouter(providers=providers)

    def test_available_with_providers(self):
        r = self._make_router()
        assert r.available is True

    def test_not_available_without_providers(self):
        r = self._make_router(providers=[])
        assert r.available is False

    def test_provider_names(self):
        r = self._make_router()
        assert "groq" in r.provider_names

    def test_send_returns_string(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="  Olá  "))]
        mock_client.chat.completions.create.return_value = mock_response

        r = self._make_router()
        r._clients["groq"] = mock_client

        result = r.send("test")
        assert result == "Olá"

    def test_send_passes_messages(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="reply"))]
        mock_client.chat.completions.create.return_value = mock_response

        r = self._make_router()
        r._clients["groq"] = mock_client

        msgs = [{"role": "user", "content": "hi"}]
        r.send("ignored", messages=msgs)

        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["messages"] == msgs

    def test_send_raises_on_all_failures(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("boom")

        r = self._make_router()
        r._clients["groq"] = mock_client

        with pytest.raises(AllProvidersFailedError):
            r.send("test")

    def test_send_skips_unavailable_providers(self):
        bad_client = MagicMock()
        bad_client.chat.completions.create.side_effect = Exception("fail")

        good_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
        good_client.chat.completions.create.return_value = mock_response

        r = self._make_router(providers=[
            ProviderConfig(name="bad", api_key="k", model="m"),
            ProviderConfig(name="good", api_key="k", model="m"),
        ])
        r._clients = {"bad": bad_client, "good": good_client}

        result = r.send("test")
        assert result == "ok"

    def test_send_capability_check(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
        mock_client.chat.completions.create.return_value = mock_response

        r = self._make_router(providers=[
            ProviderConfig(name="text_only", api_key="k", model="m", capabilities=("text",)),
            ProviderConfig(name="vision", api_key="k", model="m", capabilities=("text", "vision")),
        ])
        r._clients = {"text_only": mock_client, "vision": mock_client}

        result = r.send("describe", capabilities=["vision"])
        assert result == "ok"

    def test_send_capability_all_fail(self):
        r = self._make_router(providers=[
            ProviderConfig(name="text_only", api_key="k", model="m", capabilities=("text",)),
        ])

        with pytest.raises(AllProvidersFailedError):
            r.send("describe", capabilities=["vision"])

    def test_send_temperature_and_max_tokens(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
        mock_client.chat.completions.create.return_value = mock_response

        r = self._make_router()
        r._clients["groq"] = mock_client

        r.send("test", temperature=0.3, max_tokens=100)
        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["temperature"] == 0.3
        assert call_args.kwargs["max_tokens"] == 100

    def test_get_status(self):
        r = self._make_router()
        status = r.get_status()
        assert "providers" in status
        assert len(status["providers"]) == 1
        assert status["providers"][0]["name"] == "groq"

    def test_clear_clients(self):
        r = self._make_router()
        r._clients["groq"] = MagicMock()
        r.clear_clients()
        assert len(r._clients) == 0

    def test_send_empty_providers_raises(self):
        r = self._make_router(providers=[])
        with pytest.raises(AllProvidersFailedError, match="Nenhum provider"):
            r.send("test")

    def test_multiple_providers_failover(self):
        fail_client = MagicMock()
        fail_client.chat.completions.create.side_effect = Exception("down")

        ok_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="fallback_ok"))]
        ok_client.chat.completions.create.return_value = mock_response

        r = self._make_router(providers=[
            ProviderConfig(name="primary", api_key="k", model="m"),
            ProviderConfig(name="secondary", api_key="k", model="m"),
        ])
        r._clients = {"primary": fail_client, "secondary": ok_client}

        result = r.send("test")
        assert result == "fallback_ok"
        assert r._available["primary"] is False
