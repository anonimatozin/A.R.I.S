"""Gmail Service — Read-only integration for A.R.I.S.

OAuth2 flow + REST API calls to Gmail. Read-only scope only.
Tokens stored encrypted via SafetyManager.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Headers proibidos em outputs que vão pro LLM
_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-goog-"}


@dataclass(frozen=True)
class MessageSummary:
    id: str
    from_: str
    subject: str
    date: datetime
    snippet: str
    labels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from": self.from_,
            "subject": self.subject,
            "date": self.date.isoformat(),
            "snippet": self.snippet,
            "labels": list(self.labels),
        }


@dataclass(frozen=True)
class MessageDetail:
    id: str
    from_: str
    to: str
    subject: str
    date: datetime
    body_plain: str
    labels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from": self.from_,
            "to": self.to,
            "subject": self.subject,
            "date": self.date.isoformat(),
            "body": self.body_plain,
            "labels": list(self.labels),
        }


class GmailService:
    """Serviço Gmail read-only com OAuth2 + refresh token."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        safety_manager=None,
        account_email: str = "",
        auth_port: int = 8741,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._safety = safety_manager
        self._account = account_email
        self._auth_port = auth_port
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expiry: float = 0
        self._scope_verified: bool = False
        self._secret_key = f"gmail:{account_email}:tokens"

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None

    def get_auth_url(self) -> str:
        """Gera URL de consentimento OAuth (somente leitura)."""
        from urllib.parse import urlencode
        params = {
            "client_id": self._client_id,
            "redirect_uri": f"http://localhost:{self._auth_port}/callback",
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{GMAIL_AUTH_URL}?{urlencode(params)}"

    def start_callback_server(self, timeout: int = 120) -> str | None:
        """Inicia servidor local temporário para capturar o callback OAuth.

        Roda em background, espera o browser redirecionar com o code,
        troca por tokens e para o servidor.

        Returns:
            code se sucesso, None se timeout/erro.
        """
        import threading
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from urllib.parse import urlparse, parse_qs

        result_code: str | None = None
        server_ref: HTTPServer | None = None

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(handler_self):
                nonlocal result_code
                parsed = urlparse(handler_self.path)
                if parsed.path == "/callback":
                    params = parse_qs(parsed.query)
                    code = params.get("code", [None])[0]
                    error = params.get("error", [None])[0]

                    if code:
                        result_code = code
                        handler_self.send_response(200)
                        handler_self.send_header("Content-Type", "text/html; charset=utf-8")
                        handler_self.end_headers()
                        handler_self.wfile.write(
                            b"<html><body><h2>A.R.I.S. autenticado!</h2>"
                            b"<p>Voce pode fechar esta aba.</p>"
                            b"</body></html>"
                        )
                    else:
                        handler_self.send_response(400)
                        handler_self.send_header("Content-Type", "text/html; charset=utf-8")
                        handler_self.end_headers()
                        msg = f"Erro: {error or 'code não encontrado'}"
                        handler_self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())
                else:
                    handler_self.send_response(404)
                    handler_self.end_headers()

                # Parar servidor após receber callback
                if server_ref:
                    threading.Thread(target=server_ref.shutdown, daemon=True).start()

            def log_message(handler_self, format, *args):
                pass  # Silenciar logs do servidor

        try:
            server_ref = HTTPServer(("localhost", self._auth_port), CallbackHandler)
            server_ref.timeout = timeout
            # Rodar em thread separada
            server_thread = threading.Thread(target=server_ref.serve_forever, daemon=True)
            server_thread.start()
            # Esperar até timeout
            server_thread.join(timeout=timeout)
            server_ref.server_close()
            return result_code
        except Exception as e:
            logger.error(f"Callback server error: {e}")
            return None

    def exchange_code(self, code: str) -> bool:
        """Troca authorization code por tokens. Retorna True se sucesso."""
        try:
            resp = requests.post(
                GMAIL_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": f"http://localhost:{self._auth_port}/callback",
                    "grant_type": "authorization_code",
                },
                timeout=30,
            )
            resp.raise_for_status()
            tokens = resp.json()
            return self._process_token_response(tokens)
        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
            return False

    def _process_token_response(self, tokens: dict) -> bool:
        """Processa resposta de token, valida scopes, armazena."""
        scope_str = tokens.get("scope", "")
        scopes = scope_str.split() if scope_str else GMAIL_SCOPES

        # Verificar que NÃO tem scopes além de gmail.readonly
        allowed = {"https://www.googleapis.com/auth/gmail.readonly"}
        extra = set(scopes) - allowed
        if extra:
            logger.warning(
                f"Token has extra scopes beyond gmail.readonly: {extra}. "
                "Refusing to store."
            )
            return False

        self._access_token = tokens.get("access_token")
        self._refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)
        self._token_expiry = time.time() + expires_in - 300  # 5min margin
        self._scope_verified = True

        # Armazenar via SafetyManager
        if self._safety and self._refresh_token:
            token_data = json.dumps({
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "expiry": self._token_expiry,
                "scopes": scopes,
            })
            self._safety.store_secret(self._secret_key, token_data)

        return True

    def load_stored_tokens(self) -> bool:
        """Carrega tokens armazenados do SafetyManager."""
        if not self._safety:
            return False
        token_data = self._safety.load_secret(self._secret_key)
        if not token_data:
            return False
        try:
            data = json.loads(token_data)
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._token_expiry = data.get("expiry", 0)
            self._scope_verified = True
            return True
        except Exception:
            return False

    def _ensure_token(self) -> bool:
        """Garante que temos um access token válido. Refresh se necessário."""
        if self._access_token and time.time() < self._token_expiry:
            return True
        if self._refresh_token:
            return self._refresh_access_token()
        return False

    def _refresh_access_token(self) -> bool:
        """Refresh o access token usando o refresh token."""
        if not self._refresh_token:
            return False
        try:
            resp = requests.post(
                GMAIL_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
            if resp.status_code == 401 or resp.status_code == 403:
                logger.warning("Refresh token revoked/expired — re-auth required")
                self._access_token = None
                self._refresh_token = None
                return False
            resp.raise_for_status()
            tokens = resp.json()
            self._access_token = tokens.get("access_token")
            expires_in = tokens.get("expires_in", 3600)
            self._token_expiry = time.time() + expires_in - 300
            # Atualizar storage
            if self._safety and self._refresh_token:
                token_data = json.dumps({
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "expiry": self._token_expiry,
                })
                self._safety.store_secret(self._secret_key, token_data)
            return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False

    def _headers(self) -> dict[str, str]:
        """Headers autenticados para requests Gmail."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _api_get(self, endpoint: str, params: dict | None = None) -> dict | None:
        """GET autenticado contra Gmail API com retry em 401."""
        if not self._ensure_token():
            return None
        url = f"{GMAIL_API_BASE}/{endpoint}"
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            if resp.status_code in (401, 403):
                if self._refresh_access_token():
                    resp = requests.get(
                        url, headers=self._headers(), params=params, timeout=30
                    )
                else:
                    return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Gmail API error ({endpoint}): {e}")
            return None

    # ── Read-only verbs ────────────────────────────────────

    def list_messages(
        self, query: str = "is:unread", max_results: int = 10
    ) -> list[MessageSummary]:
        """Lista mensagens com query syntax do Gmail."""
        data = self._api_get(
            "users/me/messages",
            params={"q": query, "maxResults": max_results},
        )
        if not data:
            return []

        messages = []
        for msg_stub in data.get("messages", []):
            msg_id = msg_stub.get("id")
            if not msg_id:
                continue
            detail = self._api_get(f"users/me/messages/{msg_id}", params={"format": "metadata"})
            if detail:
                messages.append(self._parse_summary(detail))
        return messages

    def get_message(self, message_id: str) -> MessageDetail | None:
        """Retorna detalhe completo de uma mensagem."""
        data = self._api_get(
            f"users/me/messages/{message_id}",
            params={"format": "full"},
        )
        if not data:
            return None
        return self._parse_detail(data)

    def search(self, query: str, max_results: int = 10) -> list[MessageSummary]:
        """Alias para list_messages com query syntax do Gmail."""
        return self.list_messages(query=query, max_results=max_results)

    # ── Parsers ────────────────────────────────────────────

    def _parse_summary(self, data: dict) -> MessageSummary:
        """Extrai MessageSummary de metadata response."""
        headers = {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}
        date_str = headers.get("date", "")
        try:
            date = datetime.fromisoformat(date_str.replace(" +", "+").replace(" -", "-"))
        except Exception:
            date = datetime.now()
        labels = tuple(data.get("labelIds", []))
        return MessageSummary(
            id=data.get("id", ""),
            from_=headers.get("from", ""),
            subject=headers.get("subject", "(sem assunto)"),
            date=date,
            snippet=data.get("snippet", ""),
            labels=labels,
        )

    def _parse_detail(self, data: dict) -> MessageDetail:
        """Extrai MessageDetail de full response."""
        headers = {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}
        date_str = headers.get("date", "")
        try:
            date = datetime.fromisoformat(date_str.replace(" +", "+").replace(" -", "-"))
        except Exception:
            date = datetime.now()
        labels = tuple(data.get("labelIds", []))
        body_plain = self._extract_body(data.get("payload", {}))
        return MessageDetail(
            id=data.get("id", ""),
            from_=headers.get("from", ""),
            to=headers.get("to", ""),
            subject=headers.get("subject", "(sem assunto)"),
            date=date,
            body_plain=body_plain,
            labels=labels,
        )

    def _extract_body(self, payload: dict) -> str:
        """Extrai body text/plain de payload recursivo."""
        if payload.get("mimeType") == "text/plain":
            import base64
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for part in payload.get("parts", []):
            result = self._extract_body(part)
            if result:
                return result
        return ""

    # ── Account info ───────────────────────────────────────

    def _api_post(self, endpoint: str, data: dict | None = None) -> dict | None:
        """POST autenticado contra Gmail API com retry em 401."""
        if not self._ensure_token():
            return None
        url = f"{GMAIL_API_BASE}/{endpoint}"
        try:
            resp = requests.post(url, headers=self._headers(), json=data, timeout=30)
            if resp.status_code in (401, 403):
                if self._refresh_access_token():
                    resp = requests.post(url, headers=self._headers(), json=data, timeout=30)
                else:
                    return None
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except Exception as e:
            logger.error(f"Gmail API POST error ({endpoint}): {e}")
            return None

    def _api_post_empty(self, endpoint: str) -> bool:
        """POST sem body (para actions como trash). Retorna True se 200."""
        if not self._ensure_token():
            return False
        url = f"{GMAIL_API_BASE}/{endpoint}"
        try:
            resp = requests.post(url, headers=self._headers(), timeout=30)
            if resp.status_code in (401, 403):
                if self._refresh_access_token():
                    resp = requests.post(url, headers=self._headers(), timeout=30)
                else:
                    return False
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Gmail API POST empty error ({endpoint}): {e}")
            return False

    def trash_message(self, message_id: str) -> bool:
        """Move mensagem pra lixeira (recuperável por 30 dias)."""
        return self._api_post_empty(f"users/me/messages/{message_id}/trash")

    def untrash_message(self, message_id: str) -> bool:
        """Restaura mensagem da lixeira."""
        return self._api_post_empty(f"users/me/messages/{message_id}/untrash")

    def mark_as_read(self, message_id: str) -> bool:
        """Marca mensagem como lida (remove label UNREAD)."""
        return self._api_post(
            f"users/me/messages/{message_id}/modify",
            {"removeLabelIds": ["UNREAD"]},
        ) is not None

    def mark_as_unread(self, message_id: str) -> bool:
        """Marca mensagem como não lida (adiciona label UNREAD)."""
        return self._api_post(
            f"users/me/messages/{message_id}/modify",
            {"addLabelIds": ["UNREAD"]},
        ) is not None

    def get_account_email(self) -> str:
        """Retorna email da conta autenticada."""
        if not self._ensure_token():
            return ""
        try:
            resp = requests.get(GMAIL_USERINFO_URL, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json().get("email", "")
        except Exception:
            return self._account
