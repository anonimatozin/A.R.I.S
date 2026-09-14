"""Multi-Provider IA do A.R.I.S.

Wrapper sobre LLMRouter que mantém histórico de conversa
e fornece interface backward-compatible com o código existente.
"""

from core.llm.router import AllProvidersFailedError, LLMRouter
from utils.logger import Logger


class MultiProviderChat:
    """Gerenciador de conversas com fallback automático via LLMRouter.

    Mantém histórico de conversa e delega chamadas LLM ao router.
    """

    def __init__(self, logger: Logger | None = None, router: LLMRouter | None = None):
        self._logger = logger
        self._router = router or LLMRouter(logger=logger)
        self._history: list[dict[str, str]] = []
        self._system_prompt: str = ""

    @property
    def available(self) -> bool:
        return self._router.available

    @property
    def provider_name(self) -> str:
        status = self._router.get_status()
        providers = status.get("providers", [])
        for p in providers:
            if p.get("available"):
                return p["name"]
        return "nenhum"

    def set_system_prompt(self, prompt: str) -> None:
        self._system_prompt = prompt
        self._history = [{"role": "system", "content": prompt}]

    def _trim_history(self, messages: list[dict], max_chars: int = 6000) -> list[dict]:
        """Mantém o contexto dentro do limite do modelo (evita 413/TPM)."""
        system = messages[0] if messages and messages[0].get("role") == "system" else None
        rest = messages[1:] if system else messages
        kept = []
        budget = max_chars
        for m in reversed(rest):
            budget -= len(m.get("content", "") or "")
            if budget < 0:
                break
            kept.append(m)
        kept.reverse()
        return ([system] if system else []) + kept

    def send(self, message: str, temperature: float = 0.7, max_tokens: int = 2048) -> str:
        """Envia mensagem com fallback automático entre provedores.

        Returns:
            Resposta do provedor ou mensagem de erro (string).
        """
        self._history.append({"role": "user", "content": message})
        messages = self._trim_history(self._history)

        try:
            reply = self._router.send(
                message,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=messages,
            )
            self._history.append({"role": "assistant", "content": reply})
            return reply
        except AllProvidersFailedError as exc:
            error_msg = str(exc)
            if self._logger:
                self._logger.error(error_msg)
            return error_msg

    def clear_history(self) -> None:
        self._history = [{"role": "system", "content": self._system_prompt}]

    def get_status(self) -> dict:
        return self._router.get_status()
