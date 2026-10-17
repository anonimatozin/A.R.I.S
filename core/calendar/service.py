"""Google Calendar Service — agendamento com detecção de conflito.

OAuth2 com escopo calendar.events (leitura/escrita de eventos).
Reutiliza infraestrutura de tokens do GmailService.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]
CALENDAR_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
CALENDAR_TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@dataclass(frozen=True)
class CalendarEvent:
    """Evento do Google Calendar."""
    id: str
    summary: str
    description: str | None
    start: datetime
    end: datetime
    location: str | None = None
    attendees: tuple[str, ...] = ()
    calendar_id: str = "primary"
    html_link: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "description": self.description,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "location": self.location,
            "attendees": list(self.attendees),
            "calendar_id": self.calendar_id,
            "html_link": self.html_link,
        }

    def overlaps(self, other_start: datetime, other_end: datetime) -> bool:
        """Verifica se este evento sobrepõe com o intervalo dado."""
        return self.start < other_end and self.end > other_start


class GoogleCalendarService:
    """Serviço Google Calendar com OAuth2 + detecção de conflito."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        safety_manager=None,
        account_email: str = "",
        auth_port: int = 8742,
        gmail_service=None,  # Para reutilizar tokens se mesmo OAuth
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._safety = safety_manager
        self._account = account_email
        self._auth_port = auth_port
        self._gmail_service = gmail_service
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expiry: float = 0
        self._scope_verified: bool = False
        self._secret_key = f"calendar:{account_email}:tokens"

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None

    def get_auth_url(self) -> str:
        """Gera URL de consentimento OAuth (calendar.events + readonly)."""
        from urllib.parse import urlencode
        params = {
            "client_id": self._client_id,
            "redirect_uri": f"http://localhost:{self._auth_port}/callback",
            "response_type": "code",
            "scope": " ".join(CALENDAR_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{CALENDAR_AUTH_URL}?{urlencode(params)}"

    def start_callback_server(self, timeout: int = 120) -> str | None:
        """Inicia servidor local para callback OAuth."""
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
                            b"<html><body><h2>Google Calendar autenticado!</h2>"
                            b"<p>Voce pode fechar esta aba.</p>"
                            b"</body></html>"
                        )
                    else:
                        handler_self.send_response(400)
                        handler_self.send_header("Content-Type", "text/html; charset=utf-8")
                        handler_self.end_headers()
                        msg = f"Erro: {error or 'code nao encontrado'}"
                        handler_self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())
                else:
                    handler_self.send_response(404)
                    handler_self.end_headers()

                if server_ref:
                    threading.Thread(target=server_ref.shutdown, daemon=True).start()

            def log_message(handler_self, format, *args):
                pass

        try:
            server_ref = HTTPServer(("localhost", self._auth_port), CallbackHandler)
            server_ref.timeout = timeout
            server_thread = threading.Thread(target=server_ref.serve_forever, daemon=True)
            server_thread.start()
            server_thread.join(timeout=timeout)
            server_ref.server_close()
            return result_code
        except Exception as e:
            logger.error(f"Calendar callback server error: {e}")
            return None

    def exchange_code(self, code: str) -> bool:
        """Troca authorization code por tokens."""
        try:
            resp = requests.post(
                CALENDAR_TOKEN_URL,
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
            logger.error(f"Calendar token exchange failed: {e}")
            return False

    def _process_token_response(self, tokens: dict) -> bool:
        """Processa resposta de token, valida scopes, armazena."""
        scope_str = tokens.get("scope", "")
        scopes = scope_str.split() if scope_str else CALENDAR_SCOPES

        # Verificar que tem pelo menos calendar.readonly
        allowed = {"https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.readonly"}
        has_calendar = any(s in allowed for s in scopes)
        if not has_calendar:
            logger.warning(f"Token não tem escopo de Calendar: {scopes}")
            return False

        self._access_token = tokens.get("access_token")
        self._refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)
        self._token_expiry = time.time() + expires_in - 300
        self._scope_verified = True

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
        if self._access_token and time.time() < self._token_expiry:
            return True
        if self._refresh_token:
            return self._refresh_access_token()
        return False

    def _refresh_access_token(self) -> bool:
        if not self._refresh_token:
            return False
        try:
            resp = requests.post(
                CALENDAR_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
            if resp.status_code in (401, 403):
                logger.warning("Calendar refresh token revoked/expired")
                self._access_token = None
                self._refresh_token = None
                return False
            resp.raise_for_status()
            tokens = resp.json()
            self._access_token = tokens.get("access_token")
            expires_in = tokens.get("expires_in", 3600)
            self._token_expiry = time.time() + expires_in - 300
            if self._safety and self._refresh_token:
                token_data = json.dumps({
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "expiry": self._token_expiry,
                })
                self._safety.store_secret(self._secret_key, token_data)
            return True
        except Exception as e:
            logger.error(f"Calendar token refresh failed: {e}")
            return False

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _api_get(self, endpoint: str, params: dict | None = None) -> dict | None:
        if not self._ensure_token():
            return None
        url = f"{CALENDAR_API_BASE}/{endpoint}"
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            if resp.status_code in (401, 403):
                if self._refresh_access_token():
                    resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
                else:
                    return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Calendar API error ({endpoint}): {e}")
            return None

    def _api_post(self, endpoint: str, data: dict | None = None) -> dict | None:
        if not self._ensure_token():
            return None
        url = f"{CALENDAR_API_BASE}/{endpoint}"
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
            logger.error(f"Calendar API POST error ({endpoint}): {e}")
            return None

    def _api_delete(self, endpoint: str) -> bool:
        if not self._ensure_token():
            return False
        url = f"{CALENDAR_API_BASE}/{endpoint}"
        try:
            resp = requests.delete(url, headers=self._headers(), timeout=30)
            if resp.status_code in (401, 403):
                if self._refresh_access_token():
                    resp = requests.delete(url, headers=self._headers(), timeout=30)
                else:
                    return False
            return resp.status_code == 204
        except Exception as e:
            logger.error(f"Calendar API DELETE error ({endpoint}): {e}")
            return False

    # ── Event Operations ─────────────────────────────────────

    def list_events(
        self,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 50,
        calendar_id: str = "primary",
        query: str | None = None,
    ) -> list[CalendarEvent]:
        """Lista eventos no intervalo."""
        params = {
            "maxResults": min(max_results, 250),
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        if time_min:
            params["timeMin"] = time_min.isoformat() + "Z"
        if time_max:
            params["timeMax"] = time_max.isoformat() + "Z"
        if query:
            params["q"] = query

        data = self._api_get(f"calendars/{calendar_id}/events", params=params)
        if not data:
            return []

        events = []
        for item in data.get("items", []):
            evt = self._parse_event(item, calendar_id)
            if evt:
                events.append(evt)
        return events

    def get_event(self, event_id: str, calendar_id: str = "primary") -> CalendarEvent | None:
        """Obtém evento específico."""
        data = self._api_get(f"calendars/{calendar_id}/events/{event_id}")
        if not data:
            return None
        return self._parse_event(data, calendar_id)

    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        calendar_id: str = "primary",
        reminders: list[dict] | None = None,
    ) -> CalendarEvent | None:
        """Cria novo evento. Retorna evento criado ou None se falhou."""
        event_data = {
            "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": "America/Sao_Paulo"},
            "end": {"dateTime": end.isoformat(), "timeZone": "America/Sao_Paulo"},
        }
        if description:
            event_data["description"] = description
        if location:
            event_data["location"] = location
        if attendees:
            event_data["attendees"] = [{"email": a} for a in attendees]
        if reminders:
            event_data["reminders"] = {"useDefault": False, "overrides": reminders}

        data = self._api_post(f"calendars/{calendar_id}/events", data=event_data)
        if not data:
            return None
        return self._parse_event(data, calendar_id)

    def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        **updates,
    ) -> CalendarEvent | None:
        """Atualiza evento existente."""
        # Primeiro busca o evento atual
        current = self.get_event(event_id, calendar_id)
        if not current:
            return None

        event_data = {
            "summary": updates.get("summary", current.summary),
            "description": updates.get("description", current.description),
            "location": updates.get("location", current.location),
            "start": {"dateTime": updates.get("start", current.start).isoformat(), "timeZone": "America/Sao_Paulo"},
            "end": {"dateTime": updates.get("end", current.end).isoformat(), "timeZone": "America/Sao_Paulo"},
        }
        if "attendees" in updates:
            event_data["attendees"] = [{"email": a} for a in updates["attendees"]]

        data = self._api_post(f"calendars/{calendar_id}/events/{event_id}", data=event_data)
        if not data:
            return None
        return self._parse_event(data, calendar_id)

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """Deleta evento (move para lixeira do Calendar)."""
        return self._api_delete(f"calendars/{calendar_id}/events/{event_id}")

    # ── Conflict Detection ───────────────────────────────────

    def check_conflicts(
        self,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
        exclude_event_id: str | None = None,
    ) -> list[CalendarEvent]:
        """Verifica conflitos no intervalo [start, end).

        Retorna lista de eventos que sobrepõem.
        """
        # Buscar eventos no intervalo expandido (buffer de 1 min)
        buffer_start = start - timedelta(minutes=1)
        buffer_end = end + timedelta(minutes=1)

        events = self.list_events(time_min=buffer_start, time_max=buffer_end, calendar_id=calendar_id)

        conflicts = []
        for evt in events:
            if exclude_event_id and evt.id == exclude_event_id:
                continue
            if evt.overlaps(start, end):
                conflicts.append(evt)

        return conflicts

    def find_free_slots(
        self,
        date: datetime,
        duration_minutes: int = 60,
        work_start_hour: int = 9,
        work_end_hour: int = 18,
        calendar_id: str = "primary",
    ) -> list[tuple[datetime, datetime]]:
        """Encontra horários livres no dia."""
        day_start = date.replace(hour=work_start_hour, minute=0, second=0, microsecond=0)
        day_end = date.replace(hour=work_end_hour, minute=0, second=0, microsecond=0)

        events = self.list_events(time_min=day_start, time_max=day_end, calendar_id=calendar_id)
        busy = [(e.start, e.end) for e in events]
        busy.sort()

        free_slots = []
        current = day_start

        for busy_start, busy_end in busy:
            if current + timedelta(minutes=duration_minutes) <= busy_start:
                free_slots.append((current, busy_start))
            current = max(current, busy_end)

        if current + timedelta(minutes=duration_minutes) <= day_end:
            free_slots.append((current, day_end))

        return free_slots

    # ── Parsers ──────────────────────────────────────────────

    def _parse_event(self, data: dict, calendar_id: str) -> CalendarEvent | None:
        try:
            start_data = data.get("start", {})
            end_data = data.get("end", {})

            start_str = start_data.get("dateTime") or start_data.get("date")
            end_str = end_data.get("dateTime") or end_data.get("date")

            if not start_str or not end_str:
                return None

            # Parse ISO format
            if "T" in start_str:
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            else:
                start = datetime.fromisoformat(start_str + "T00:00:00")

            if "T" in end_str:
                end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            else:
                end = datetime.fromisoformat(end_str + "T23:59:59")

            attendees = tuple(
                a.get("email", "") for a in data.get("attendees", []) if a.get("email")
            )

            return CalendarEvent(
                id=data.get("id", ""),
                summary=data.get("summary", "(sem título)"),
                description=data.get("description"),
                start=start,
                end=end,
                location=data.get("location"),
                attendees=attendees,
                calendar_id=calendar_id,
                html_link=data.get("htmlLink"),
            )
        except Exception as e:
            logger.error(f"Failed to parse calendar event: {e}")
            return None


# ── Multi-Account Manager (similar to GmailManager) ───────────

@dataclass(frozen=True)
class CalendarAccountConfig:
    account_id: str
    display_name: str
    client_id: str
    client_secret: str
    account_email: str = ""
    auth_port: int = 8742


class CalendarManager:
    """Gerenciador multi-conta para Google Calendar."""

    def __init__(self, safety_manager=None):
        self._safety = safety_manager
        self._accounts: dict[str, GoogleCalendarService] = {}
        self._configs: dict[str, CalendarAccountConfig] = {}
        self._default_account_id: str | None = None

    def add_account(self, config: CalendarAccountConfig, gmail_service=None) -> bool:
        if config.account_id in self._accounts:
            self.remove_account(config.account_id)

        service = GoogleCalendarService(
            client_id=config.client_id,
            client_secret=config.client_secret,
            safety_manager=self._safety,
            account_email=config.account_email,
            auth_port=config.auth_port,
            gmail_service=gmail_service,
        )
        self._accounts[config.account_id] = service
        self._configs[config.account_id] = config

        if self._default_account_id is None:
            self._default_account_id = config.account_id

        return True

    def remove_account(self, account_id: str) -> bool:
        if account_id in self._accounts:
            del self._accounts[account_id]
            del self._configs[account_id]
            if self._default_account_id == account_id:
                self._default_account_id = next(iter(self._accounts)) if self._accounts else None
            return True
        return False

    def get_service(self, account_id: str | None = None) -> GoogleCalendarService | None:
        aid = account_id or self._default_account_id
        return self._accounts.get(aid) if aid else None

    def get_default_account_id(self) -> str | None:
        return self._default_account_id

    def set_default(self, account_id: str) -> bool:
        if account_id in self._accounts:
            self._default_account_id = account_id
            return True
        return False

    def list_accounts(self) -> list[dict]:
        return [
            {
                "account_id": aid,
                "display_name": self._configs[aid].display_name,
                "account_email": self._configs[aid].account_email,
                "is_configured": svc.is_configured,
                "is_authenticated": svc.is_authenticated,
            }
            for aid, svc in self._accounts.items()
        ]

    def get_auth_url(self, account_id: str | None = None) -> str | None:
        svc = self.get_service(account_id)
        return svc.get_auth_url() if svc else None

    def handle_callback(self, account_id: str, code: str) -> bool:
        svc = self._accounts.get(account_id)
        return svc.exchange_code(code) if svc else False

    def load_all_tokens(self) -> dict[str, bool]:
        return {aid: svc.load_stored_tokens() for aid, svc in self._accounts.items()}

    # Convenience methods delegating to default account
    def list_events(self, *args, account_id: str | None = None, **kwargs) -> list[CalendarEvent]:
        svc = self.get_service(account_id)
        return svc.list_events(*args, **kwargs) if svc else []

    def check_conflicts(self, *args, account_id: str | None = None, **kwargs) -> list[CalendarEvent]:
        svc = self.get_service(account_id)
        return svc.check_conflicts(*args, **kwargs) if svc else []

    def create_event(self, *args, account_id: str | None = None, **kwargs) -> CalendarEvent | None:
        svc = self.get_service(account_id)
        return svc.create_event(*args, **kwargs) if svc else None

    def find_free_slots(self, *args, account_id: str | None = None, **kwargs):
        svc = self.get_service(account_id)
        return svc.find_free_slots(*args, **kwargs) if svc else []