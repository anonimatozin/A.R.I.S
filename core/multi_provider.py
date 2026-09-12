"""Multi-Provider IA do A.R.I.S.

Suporta múltiplos provedores de IA com fallback automático:
Groq, Google Gemini, Ollama (local).
"""

import os
import json
from typing import Optional
from openai import OpenAI

from utils.logger import Logger
from core.rate_limiter import groq_limiter, gemini_limiter, ollama_limiter


class AIProvider:
    """Representa um provedor de IA."""

    def __init__(self, name: str, client: OpenAI, model: str, base_url: str = ""):
        self.name = name
        self.client = client
        self.model = model
        self.base_url = base_url
        self.available = True


class MultiProviderChat:
    """Gerenciador de múltiplos provedores de IA com fallback automático.

    Tenta o provedor primário; se falhar, tenta o próximo na lista.
    """

    def __init__(self, logger: Optional[Logger] = None):
        self._logger = logger
        self._providers: list[AIProvider] = []
        self._current_index = 0
        self._history: list[dict[str, str]] = []
        self._system_prompt: str = ""

        self._init_providers()

    def _init_providers(self) -> None:
        """Inicializa todos os provedores configurados."""
        # Groq (primário)
        groq_key = os.getenv("GROQ_API_KEY", "")
        if groq_key:
            try:
                client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
                model = os.getenv("ARIS_CHAT_MODEL", "llama-3.3-70b-versatile")
                self._providers.append(AIProvider("groq", client, model))
                if self._logger:
                    self._logger.info(f"Provider Groq inicializado: {model}")
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"Falha ao inicializar Groq: {e}")

        # Google Gemini
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                client = OpenAI(api_key=gemini_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
                model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
                self._providers.append(AIProvider("gemini", client, model))
                if self._logger:
                    self._logger.info(f"Provider Gemini inicializado: {model}")
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"Falha ao inicializar Gemini: {e}")

        # Ollama (local)
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2")
        try:
            client = OpenAI(api_key="ollama", base_url=ollama_url)
            # Testar conexão
            client.models.list()
            self._providers.append(AIProvider("ollama", client, ollama_model, ollama_url))
            if self._logger:
                self._logger.info(f"Provider Ollama inicializado: {ollama_model}")
        except Exception:
            if self._logger:
                self._logger.debug("Ollama não disponível (local offline)")

    @property
    def available(self) -> bool:
        """Verifica se há pelo menos um provedor disponível."""
        return len(self._providers) > 0

    @property
    def current_provider(self) -> Optional[AIProvider]:
        """Retorna o provedor atualmente ativo."""
        if self._providers:
            return self._providers[self._current_index % len(self._providers)]
        return None

    @property
    def provider_name(self) -> str:
        """Nome do provedor atual."""
        p = self.current_provider
        return p.name if p else "nenhum"

    def set_system_prompt(self, prompt: str) -> None:
        """Define o system prompt para todos os provedores."""
        self._system_prompt = prompt
        self._history = [{"role": "system", "content": prompt}]

    _RATE_LIMITERS = {
        "groq": groq_limiter,
        "gemini": gemini_limiter,
        "ollama": ollama_limiter,
    }

    def send(self, message: str, temperature: float = 0.7, max_tokens: int = 2048) -> str:
        """Envia mensagem com fallback automático entre provedores.

        Args:
            message: Mensagem do usuário.
            temperature: Temperatura de geração.
            max_tokens: Máximo de tokens na resposta.

        Returns:
            Resposta do provedor ou mensagem de erro.
        """
        if not self._providers:
            return "Nenhum provedor de IA configurado. Defina GROQ_API_KEY, GEMINI_API_KEY ou instale Ollama."

        self._history.append({"role": "user", "content": message})

        # Tentar cada provedor em sequência
        last_error = None
        for i in range(len(self._providers)):
            provider_idx = (self._current_index + i) % len(self._providers)
            provider = self._providers[provider_idx]

            if not provider.available:
                continue

            # Rate limit check
            limiter = self._RATE_LIMITERS.get(provider.name)
            if limiter and not limiter.allow():
                if self._logger:
                    self._logger.warning(f"Rate limit atingido para {provider.name} ({limiter.remaining}/{limiter.max_calls})")
                continue

            try:
                messages = list(self._history)
                response = provider.client.chat.completions.create(
                    model=provider.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                reply = response.choices[0].message.content.strip()
                self._history.append({"role": "assistant", "content": reply})

                # Se funcionou com provedor diferente, atualizar índice
                if provider_idx != self._current_index:
                    self._current_index = provider_idx
                    if self._logger:
                        self._logger.info(f"Fallback para provider: {provider.name}")

                if self._logger:
                    self._logger.debug(f"Chat [{provider.name}]: reply={reply[:80]}...")

                return reply

            except Exception as e:
                last_error = e
                provider.available = False
                if self._logger:
                    self._logger.warning(f"Provider {provider.name} falhou: {e}")
                continue

        # Todos falharam
        error_msg = f"Todos os provedores falharam. Último erro: {last_error}"
        if self._logger:
            self._logger.error(error_msg)
        return error_msg

    def clear_history(self) -> None:
        """Limpa o histórico mantendo o system prompt."""
        self._history = [{"role": "system", "content": self._system_prompt}]

    def get_status(self) -> dict:
        """Retorna status de todos os provedores."""
        return {
            "providers": [
                {"name": p.name, "model": p.model, "available": p.available}
                for p in self._providers
            ],
            "current": self.provider_name,
        }
