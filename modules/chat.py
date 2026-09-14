"""Módulo de chat do A.R.I.S.

Gerencia conversas com o modelo de linguagem via LLMRouter.
Suporta RAG (injeção de memórias relevantes no contexto).
"""

from typing import TYPE_CHECKING

from config.personality import ARIS_PERSONALITY
from core.llm.router import AllProvidersFailedError, LLMRouter, ProviderConfig
from utils.logger import Logger

if TYPE_CHECKING:
    from core.memory import MemoryManager


class Chat:
    """Gerenciador de conversas com IA via LLMRouter.

    Args:
        api_key: Chave da API (fallback se router não fornecido).
        model: Modelo a ser utilizado (fallback se router não fornecido).
        system_prompt: Prompt de sistema do assistente.
        logger: Instância do logger.
        memory: Instância do MemoryManager para RAG.
        router: LLMRouter externo (senão, cria um com Groq-only).
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "openai/gpt-oss-120b",
        system_prompt: str = "",
        logger: Logger | None = None,
        memory: "MemoryManager | None" = None,
        router: LLMRouter | None = None,
    ) -> None:
        self._logger = logger
        self._model = model
        self._history: list[dict[str, str]] = []
        self._memory = memory
        self._system_prompt = system_prompt or ARIS_PERSONALITY

        if router is not None:
            self._router = router
        elif api_key:
            self._router = LLMRouter(
                providers=[ProviderConfig(
                    name="groq",
                    api_key=api_key,
                    model=model,
                    base_url="https://api.groq.com/openai/v1",
                    capabilities=("text",),
                )],
                logger=logger,
            )
        else:
            if self._logger:
                self._logger.error("Nenhum provider LLM configurado.")
            self._router = LLMRouter(providers=[], logger=logger)

        self._history.append({
            "role": "system",
            "content": self._system_prompt,
        })

    @property
    def available(self) -> bool:
        return self._router.available

    def _build_context(self, message: str) -> list[dict[str, str]]:
        """Constrói o contexto com memórias relevantes (RAG)."""
        messages = list(self._history)

        if not self._memory:
            return messages

        relevant = self._memory.search(query=message, limit=5)
        if not relevant:
            return messages

        memory_context = "\n\n## Memórias relevantes:\n"
        for mem in relevant:
            memory_context += f"- [{mem.category.value}] {mem.content}\n"

        system_msg = messages[0].copy()
        system_msg["content"] = self._system_prompt + memory_context
        messages[0] = system_msg

        return messages

    def send(self, message: str) -> str:
        """Envia uma mensagem e retorna a resposta."""
        self._history.append({"role": "user", "content": message})
        messages = self._build_context(message)

        try:
            reply = self._router.send(
                message,
                temperature=0.7,
                max_tokens=2048,
                messages=messages,
            )
            self._history.append({"role": "assistant", "content": reply})

            if self._logger:
                self._logger.debug(f"Chat: user={message[:50]}... reply={reply[:50]}...")

            return reply

        except AllProvidersFailedError as exc:
            error_msg = str(exc)
            if self._logger:
                self._logger.error(error_msg)
            return error_msg

    def clear_history(self) -> None:
        self._history = [{"role": "system", "content": self._system_prompt}]
        if self._logger:
            self._logger.debug("Histórico de conversa limpo.")

    def set_model(self, model: str) -> None:
        self._model = model
        if self._logger:
            self._logger.info(f"Modelo alterado para: {model}")
