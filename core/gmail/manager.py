"""Gmail Manager — multi-account Gmail integration for A.R.I.S.

Gerencia múltiplas contas Gmail não-pessoais com OAuth2 isolado por conta.
Reaproveita GmailService existente (read-only, síntese, classificação).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from core.gmail.service import GmailService, MessageSummary, MessageDetail

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GmailAccountConfig:
    """Configuração de uma conta Gmail."""
    account_id: str              # ID interno único (ex: "work", "project")
    display_name: str            # Nome amigável (ex: "Trabalho", "Projetos")
    client_id: str
    client_secret: str
    account_email: str = ""      # Email esperado (validação opcional)
    auth_port: int = 8741        # Porta callback OAuth (diferente por conta)


@dataclass
class AccountStatus:
    """Status de uma conta no manager."""
    config: GmailAccountConfig
    service: GmailService
    is_configured: bool = False
    is_authenticated: bool = False
    last_error: str | None = None


class GmailManager:
    """Gerenciador de múltiplas contas Gmail.

    Cada conta tem OAuth2 isolado — tokens não são compartilhados.
    Expõe API unificada para listar/buscar/ler across contas.
    """

    def __init__(self, safety_manager=None):
        self._safety = safety_manager
        self._accounts: dict[str, AccountStatus] = {}
        self._default_account_id: str | None = None

    def add_account(self, config: GmailAccountConfig) -> bool:
        """Adiciona uma conta ao manager."""
        if config.account_id in self._accounts:
            logger.warning(f"Conta {config.account_id} já existe, atualizando...")
            self.remove_account(config.account_id)

        service = GmailService(
            client_id=config.client_id,
            client_secret=config.client_secret,
            safety_manager=self._safety,
            account_email=config.account_email,
            auth_port=config.auth_port,
        )

        status = AccountStatus(
            config=config,
            service=service,
            is_configured=service.is_configured,
        )
        self._accounts[config.account_id] = status

        if self._default_account_id is None:
            self._default_account_id = config.account_id

        logger.info(f"Conta Gmail adicionada: {config.account_id} ({config.display_name})")
        return True

    def remove_account(self, account_id: str) -> bool:
        """Remove uma conta."""
        if account_id in self._accounts:
            del self._accounts[account_id]
            if self._default_account_id == account_id:
                self._default_account_id = next(iter(self._accounts)) if self._accounts else None
            return True
        return False

    def get_account(self, account_id: str) -> AccountStatus | None:
        return self._accounts.get(account_id)

    def list_accounts(self) -> list[dict[str, Any]]:
        """Lista todas as contas com status."""
        return [
            {
                "account_id": acc_id,
                "display_name": status.config.display_name,
                "account_email": status.config.account_email,
                "is_configured": status.is_configured,
                "is_authenticated": status.is_authenticated,
                "last_error": status.last_error,
            }
            for acc_id, status in self._accounts.items()
        ]

    def set_default(self, account_id: str) -> bool:
        if account_id in self._accounts:
            self._default_account_id = account_id
            return True
        return False

    @property
    def default_account_id(self) -> str | None:
        return self._default_account_id

    def _get_service(self, account_id: str | None) -> GmailService | None:
        """Obtém service de uma conta (ou default)."""
        aid = account_id or self._default_account_id
        if not aid:
            return None
        status = self._accounts.get(aid)
        return status.service if status else None

    def _resolve_account(self, account_id: str | None) -> str | None:
        """Resolve account_id: se None, usa default; se 'all', retorna None para indicar todas."""
        if account_id == "all":
            return None
        return account_id or self._default_account_id

    # ── OAuth Flow ────────────────────────────────────────────

    def get_auth_url(self, account_id: str | None = None) -> str | None:
        """Gera URL de autorização para uma conta."""
        aid = self._resolve_account(account_id)
        if aid is None:
            return None
        service = self._get_service(aid)
        if not service:
            return None
        return service.get_auth_url()

    def start_callback_server(self, account_id: str | None = None, timeout: int = 120) -> str | None:
        """Inicia servidor callback para uma conta."""
        aid = self._resolve_account(account_id)
        if aid is None:
            return None
        status = self._accounts.get(aid)
        if not status:
            return None
        code = status.service.start_callback_server(timeout=timeout)
        if code:
            ok = status.service.exchange_code(code)
            status.is_authenticated = ok
            if not ok:
                status.last_error = "Falha ao trocar código por tokens"
        return code

    def handle_callback(self, account_id: str, code: str) -> bool:
        """Processa callback OAuth para uma conta específica."""
        status = self._accounts.get(account_id)
        if not status:
            return False
        ok = status.service.exchange_code(code)
        status.is_authenticated = ok
        if not ok:
            status.last_error = "Código inválido ou expirado"
        return ok

    def load_all_tokens(self) -> dict[str, bool]:
        """Carrega tokens salvos para todas as contas."""
        results = {}
        for aid, status in self._accounts.items():
            ok = status.service.load_stored_tokens()
            status.is_authenticated = ok
            results[aid] = ok
        return results

    # ── Read Operations (Multi-Account) ──────────────────────

    def list_messages(
        self,
        query: str = "is:unread",
        max_results: int = 10,
        account_id: str | None = None,
    ) -> dict[str, list[MessageSummary]]:
        """Lista mensagens de uma conta ou de todas."""
        aid = self._resolve_account(account_id)
        results = {}

        if aid is None:
            # Todas as contas
            for acc_id, status in self._accounts.items():
                if not status.service.is_authenticated:
                    continue
                msgs = status.service.list_messages(query=query, max_results=max_results)
                if msgs:
                    results[acc_id] = msgs
        else:
            service = self._get_service(aid)
            if service and service.is_authenticated:
                results[aid] = service.list_messages(query=query, max_results=max_results)

        return results

    def search(
        self,
        query: str,
        max_results: int = 10,
        account_id: str | None = None,
    ) -> dict[str, list[MessageSummary]]:
        """Busca mensagens em uma conta ou todas."""
        return self.list_messages(query=query, max_results=max_results, account_id=account_id)

    def get_message(
        self,
        message_id: str,
        account_id: str | None = None,
    ) -> MessageDetail | None:
        """Lê mensagem detalhada. Tenta na conta especificada ou procura em todas."""
        aid = self._resolve_account(account_id)

        if aid is not None:
            service = self._get_service(aid)
            if service and service.is_authenticated:
                return service.get_message(message_id)
            return None

        # Procurar em todas as contas
        for acc_id, status in self._accounts.items():
            if status.service.is_authenticated:
                msg = status.service.get_message(message_id)
                if msg:
                    return msg
        return None

    # ── Write Operations (Require Confirmation) ──────────────

    def mark_as_read(self, message_id: str, account_id: str | None = None) -> bool:
        aid = self._resolve_account(account_id)
        if aid is None:
            return False
        service = self._get_service(aid)
        if service and service.is_authenticated:
            return service.mark_as_read(message_id)
        return False

    def mark_as_unread(self, message_id: str, account_id: str | None = None) -> bool:
        aid = self._resolve_account(account_id)
        if aid is None:
            return False
        service = self._get_service(aid)
        if service and service.is_authenticated:
            return service.mark_as_unread(message_id)
        return False

    def trash_message(self, message_id: str, account_id: str | None = None) -> bool:
        aid = self._resolve_account(account_id)
        if aid is None:
            return False
        service = self._get_service(aid)
        if service and service.is_authenticated:
            return service.trash_message(message_id)
        return False

    def untrash_message(self, message_id: str, account_id: str | None = None) -> bool:
        aid = self._resolve_account(account_id)
        if aid is None:
            return False
        service = self._get_service(aid)
        if service and service.is_authenticated:
            return service.untrash_message(message_id)
        return False

    # ── Account Info ────────────────────────────────────────

    def get_account_emails(self) -> dict[str, str]:
        """Retorna emails das contas autenticadas."""
        emails = {}
        for aid, status in self._accounts.items():
            if status.service.is_authenticated:
                emails[aid] = status.service.get_account_email()
        return emails

    # ── Synthesis Helpers ───────────────────────────────────

    def synthesize_all(
        self,
        query: str = "is:unread",
        max_results: int = 10,
        account_id: str | None = None,
    ) -> str:
        """Gera síntese unificada de múltiplas contas."""
        from core.handlers import _synthesize_emails

        all_messages = self.list_messages(query=query, max_results=max_results, account_id=account_id)

        if not all_messages:
            return "Nenhuma mensagem encontrada em nenhuma conta."

        # Agrupar por conta para síntese
        parts = []
        for acc_id, messages in all_messages.items():
            if not messages:
                continue
            status = self._accounts[acc_id]
            account_label = status.config.display_name or acc_id
            part = _synthesize_emails(messages, f"Conta: {account_label} | Filtro: {query}")
            parts.append(f"=== {account_label} ===\n{part}")

        return "\n\n".join(parts) if parts else "Nenhuma mensagem encontrada."

    def get_combined_importance(
        self,
        query: str = "is:unread",
        max_results: int = 10,
    ) -> list[tuple[MessageSummary, int, str]]:
        """Retorna mensagens de todas as contas com importância e conta de origem."""
        from core.handlers import _classify_importance

        all_messages = self.list_messages(query=query, max_results=max_results, account_id=None)
        result = []

        for acc_id, messages in all_messages.items():
            status = self._accounts[acc_id]
            account_label = status.config.display_name or acc_id
            for msg in messages:
                importance = _classify_importance(msg)
                result.append((msg, importance, account_label))

        # Ordenar por importância decrescente
        result.sort(key=lambda x: x[1], reverse=True)
        return result