"""Email Tools — leitura de email (Edge-safe).

Credenciais nunca vao pro LLM — armazenamento seguro separado.
Suporta Gmail e Outlook. Envio fica para depois (sempre com confirmacao).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any


class EmailCredentials:
    """Armazena credenciais de email de forma segura.

    Credenciais sao salvas em arquivo criptografado separado.
    O LLM so ve o resultado das operacoes, nunca as credenciais.
    """

    def __init__(self, credentials_path: str | None = None) -> None:
        self._path = credentials_path or os.path.join(
            os.path.expanduser("~"), ".config", "aris", "email_credentials.json"
        )
        self._credentials: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, encoding="utf-8") as f:
                    self._credentials = json.load(f)
        except Exception:
            self._credentials = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._credentials, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def store(self, provider: str, email: str, token_data: dict[str, Any]) -> None:
        """Armazena credenciais de um provedor."""
        self._credentials[provider] = {
            "email": email,
            "token_data": token_data,
            "stored_at": time.time(),
        }
        self._save()

    def get(self, provider: str) -> dict[str, Any] | None:
        """Retorna credenciais de um provedor (NUNCA expoe ao LLM)."""
        return self._credentials.get(provider)

    def has_provider(self, provider: str) -> bool:
        return provider in self._credentials

    def list_providers(self) -> list[str]:
        return list(self._credentials.keys())

    def remove(self, provider: str) -> bool:
        if provider in self._credentials:
            del self._credentials[provider]
            self._save()
            return True
        return False


class EmailHandler:
    """Handler de email com suporte a Gmail e Outlook.

    Apenas operacoes de leitura nesta fase.
    Envio/reply/archive exigem confirmacao explícita (fase futura).
    """

    def __init__(self, credentials: EmailCredentials | None = None) -> None:
        self._credentials = credentials or EmailCredentials()
        self._gmail_handler = None
        self._outlook_handler = None

    def _get_gmail(self) -> Any:
        """Retorna handler do Gmail (lazy init)."""
        if self._gmail_handler is not None:
            return self._gmail_handler
        try:
            from core.gmail.handler import GmailHandler
            self._gmail_handler = GmailHandler()
            return self._gmail_handler
        except ImportError:
            return None

    def status(self) -> dict[str, Any]:
        """Status do email."""
        providers = self._credentials.list_providers()
        return {
            "ok": True,
            "configured": len(providers) > 0,
            "providers": providers,
        }

    def list_emails(self, provider: str = "gmail", folder: str = "inbox",
                    max_results: int = 20) -> dict[str, Any]:
        """Lista emails (apenas leitura)."""
        if not self._credentials.has_provider(provider):
            return {"ok": False, "error": f"Provider '{provider}' not configured"}

        if provider == "gmail":
            handler = self._get_gmail()
            if handler is None:
                return {"ok": False, "error": "Gmail handler not available"}
            try:
                emails = handler.list_emails(folder=folder, max_results=max_results)
                return {"ok": True, "emails": emails, "count": len(emails)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        return {"ok": False, "error": f"Provider '{provider}' not supported yet"}

    def search_emails(self, query: str, provider: str = "gmail",
                      max_results: int = 20) -> dict[str, Any]:
        """Busca emails."""
        if not self._credentials.has_provider(provider):
            return {"ok": False, "error": f"Provider '{provider}' not configured"}

        if provider == "gmail":
            handler = self._get_gmail()
            if handler is None:
                return {"ok": False, "error": "Gmail handler not available"}
            try:
                emails = handler.search(query=query, max_results=max_results)
                return {"ok": True, "emails": emails, "count": len(emails)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        return {"ok": False, "error": f"Provider '{provider}' not supported yet"}

    def read_email(self, email_id: str, provider: str = "gmail") -> dict[str, Any]:
        """Le um email especifico."""
        if not self._credentials.has_provider(provider):
            return {"ok": False, "error": f"Provider '{provider}' not configured"}

        if provider == "gmail":
            handler = self._get_gmail()
            if handler is None:
                return {"ok": False, "error": "Gmail handler not available"}
            try:
                email_data = handler.read_email(email_id)
                return {"ok": True, "email": email_data}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        return {"ok": False, "error": f"Provider '{provider}' not supported yet"}

    def mark_read(self, email_id: str, provider: str = "gmail") -> dict[str, Any]:
        """Marca email como lido."""
        if not self._credentials.has_provider(provider):
            return {"ok": False, "error": f"Provider '{provider}' not configured"}

        if provider == "gmail":
            handler = self._get_gmail()
            if handler is None:
                return {"ok": False, "error": "Gmail handler not available"}
            try:
                handler.mark_read(email_id)
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        return {"ok": False, "error": f"Provider '{provider}' not supported yet"}


EMAIL_TOOLS: dict[str, dict[str, Any]] = {
    "email_status": {"permission": "safe", "description": "Status do email"},
    "email_list": {"permission": "safe", "description": "Listar emails"},
    "email_search": {"permission": "safe", "description": "Buscar emails"},
    "email_read": {"permission": "safe", "description": "Ler email"},
    "email_mark_read": {"permission": "safe", "description": "Marcar como lido"},
}


def execute_email_tool(name: str, params: dict[str, Any] | None = None,
                       handler: EmailHandler | None = None) -> dict[str, Any]:
    """Executa uma tool de email."""
    if handler is None:
        handler = EmailHandler()
    params = params or {}

    if name == "email_status":
        return handler.status()
    elif name == "email_list":
        return handler.list_emails(
            provider=params.get("provider", "gmail"),
            folder=params.get("folder", "inbox"),
            max_results=params.get("max_results", 20),
        )
    elif name == "email_search":
        return handler.search_emails(
            query=params.get("query", ""),
            provider=params.get("provider", "gmail"),
            max_results=params.get("max_results", 20),
        )
    elif name == "email_read":
        return handler.read_email(
            email_id=params.get("email_id", ""),
            provider=params.get("provider", "gmail"),
        )
    elif name == "email_mark_read":
        return handler.mark_read(
            email_id=params.get("email_id", ""),
            provider=params.get("provider", "gmail"),
        )
    else:
        return {"ok": False, "error": f"Unknown email tool: {name}"}
