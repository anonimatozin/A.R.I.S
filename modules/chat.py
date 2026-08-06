"""Módulo de chat do J.A.R.V.I.S.

Gerencia conversas com o modelo de linguagem via Groq API.
Suporta RAG (injeção de memórias relevantes no contexto).
"""

import os
from typing import TYPE_CHECKING
from openai import OpenAI

from config.personality import JARVIS_PERSONALITY
from utils.logger import Logger

if TYPE_CHECKING:
    from core.memory import MemoryManager


class Chat:
    """Gerenciador de conversas com IA.

    Args:
        api_key: Chave da API Groq.
        model: Modelo a ser utilizado.
        system_prompt: Prompt de sistema do assistente.
        logger: Instância do logger.
        memory: Instância do MemoryManager para RAG.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        system_prompt: str = "",
        logger: Logger | None = None,
        memory: "MemoryManager | None" = None,
    ) -> None:
        self._logger = logger
        self._model = model
        self._history: list[dict[str, str]] = []
        self._memory = memory

        self._system_prompt = system_prompt or JARVIS_PERSONALITY

        if not api_key:
            if self._logger:
                self._logger.error("GROQ_API_KEY não configurada.")
            self._client = None
            return

        self._client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )

        self._history.append({
            "role": "system",
            "content": self._system_prompt,
        })

    @property
    def available(self) -> bool:
        """Verifica se o chat está disponível."""
        return self._client is not None

    def _build_context(self, message: str) -> list[dict[str, str]]:
        """Constrói o contexto com memórias relevantes (RAG).

        Args:
            message: Mensagem do usuário.

        Returns:
            Lista de mensagens para enviar à API.
        """
        messages = list(self._history)

        if not self._memory:
            return messages

        # Buscar memórias relevantes
        relevant = self._memory.search(query=message, limit=5)
        if not relevant:
            return messages

        # Montar contexto de memórias
        memory_context = "\n\n## Memórias relevantes:\n"
        for mem in relevant:
            memory_context += f"- [{mem.category.value}] {mem.content}\n"

        # Injetar no system prompt (após a personalidade)
        system_msg = messages[0].copy()
        system_msg["content"] = self._system_prompt + memory_context
        messages[0] = system_msg

        return messages

    def send(self, message: str) -> str:
        """Envia uma mensagem e retorna a resposta.

        Args:
            message: Mensagem do usuário.

        Returns:
            Resposta do assistente.
        """
        if not self._client:
            return "Erro: API não configurada. Defina GROQ_API_KEY no .env"

        self._history.append({"role": "user", "content": message})

        # Construir contexto com RAG
        messages = self._build_context(message)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.7,
                max_tokens=2048,
            )

            reply = response.choices[0].message.content.strip()
            self._history.append({"role": "assistant", "content": reply})

            if self._logger:
                self._logger.debug(f"Chat: user={message[:50]}... reply={reply[:50]}...")

            return reply

        except Exception as e:
            error_msg = f"Erro na API Groq: {e}"
            if self._logger:
                self._logger.error(error_msg)
            return error_msg

    def clear_history(self) -> None:
        """Limpa o histórico de conversa, mantendo o system prompt."""
        self._history = [{"role": "system", "content": self._system_prompt}]
        if self._logger:
            self._logger.debug("Histórico de conversa limpo.")

    def set_model(self, model: str) -> None:
        """Altera o modelo utilizado.

        Args:
            model: Nome do novo modelo.
        """
        self._model = model
        if self._logger:
            self._logger.info(f"Modelo alterado para: {model}")
