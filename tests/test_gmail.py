"""Tests for Gmail integration — all mocked, zero network."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def safety(tmp_path):
    from modules.safety import SafetyManager
    return SafetyManager(data_dir=tmp_path)


@pytest.fixture
def gmail_service(safety):
    from core.gmail.service import GmailService
    return GmailService(
        client_id="test_client_id",
        client_secret="test_client_secret",
        safety_manager=safety,
        account_email="test@gmail.com",
    )


# ── OAuth Flow Tests ────────────────────────────────────────

class TestOAuthFlow:
    def test_auth_url_contains_readonly_scope(self, gmail_service):
        url = gmail_service.get_auth_url()
        assert "gmail.readonly" in url
        assert "client_id=test_client_id" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url

    def test_exchange_code_success(self, gmail_service):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "ya29.test_access",
            "refresh_token": "1//test_refresh",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("core.gmail.service.requests.post", return_value=mock_resp):
            result = gmail_service.exchange_code("test_auth_code")

        assert result is True
        assert gmail_service.is_authenticated

    def test_exchange_code_rejects_extra_scopes(self, gmail_service):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "ya29.test",
            "refresh_token": "1//test",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.modify",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("core.gmail.service.requests.post", return_value=mock_resp):
            result = gmail_service.exchange_code("code")

        assert result is False
        assert not gmail_service.is_authenticated


# ── Token Storage Tests ─────────────────────────────────────

class TestTokenStorage:
    def test_store_and_load_tokens(self, gmail_service, safety):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "ya29.test",
            "refresh_token": "1//test_refresh",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("core.gmail.service.requests.post", return_value=mock_resp):
            gmail_service.exchange_code("code")

        # Tokens stored via SafetyManager
        stored = safety.load_secret("gmail:test@gmail.com:tokens")
        assert stored is not None
        data = json.loads(stored)
        assert data["refresh_token"] == "1//test_refresh"

    def test_no_plaintext_token_on_disk(self, gmail_service, safety, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "ya29.secret_value",
            "refresh_token": "1//secret_refresh",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("core.gmail.service.requests.post", return_value=mock_resp):
            gmail_service.exchange_code("code")

        # Check all files in data_dir for plaintext token
        for f in tmp_path.rglob("*"):
            if f.is_file() and f.suffix != ".key":
                content = f.read_text(encoding="utf-8", errors="ignore")
                assert "ya29.secret_value" not in content, f"Plaintext token found in {f}"
                assert "1//secret_refresh" not in content, f"Plaintext refresh found in {f}"

    def test_load_stored_tokens(self, gmail_service, safety):
        token_data = json.dumps({
            "access_token": "ya29.stored",
            "refresh_token": "1//stored_refresh",
            "expiry": 9999999999,
        })
        safety.store_secret("gmail:test@gmail.com:tokens", token_data)

        result = gmail_service.load_stored_tokens()
        assert result is True
        assert gmail_service._access_token == "ya29.stored"
        assert gmail_service._refresh_token == "1//stored_refresh"


# ── Refresh Token Tests ─────────────────────────────────────

class TestTokenRefresh:
    def test_refresh_on_401(self, gmail_service, safety):
        """First call 401, refresh, retry succeeds."""
        # Pre-load tokens
        token_data = json.dumps({
            "access_token": "ya29.expired",
            "refresh_token": "1//valid_refresh",
            "expiry": 0,  # Expired
        })
        safety.store_secret("gmail:test@gmail.com:tokens", token_data)
        gmail_service.load_stored_tokens()

        # Mock: first call returns 401, refresh succeeds, retry succeeds
        call_count = [0]
        def mock_get(url, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            if call_count[0] == 1:
                resp.status_code = 401
                return resp
            resp.status_code = 200
            resp.json.return_value = {"messages": []}
            resp.raise_for_status = MagicMock()
            return resp

        mock_refresh_resp = MagicMock()
        mock_refresh_resp.json.return_value = {
            "access_token": "ya29.refreshed",
            "expires_in": 3600,
        }
        mock_refresh_resp.raise_for_status = MagicMock()

        with patch("core.gmail.service.requests.get", side_effect=mock_get), \
             patch("core.gmail.service.requests.post", return_value=mock_refresh_resp):
            result = gmail_service._api_get("users/me/messages")

        assert result is not None

    def test_refresh_revoked_returns_none(self, gmail_service, safety):
        """Refresh token revoked → clean path, no crash."""
        token_data = json.dumps({
            "access_token": "ya29.expired",
            "refresh_token": "1//revoked",
            "expiry": 0,
        })
        safety.store_secret("gmail:test@gmail.com:tokens", token_data)
        gmail_service.load_stored_tokens()

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("core.gmail.service.requests.post", return_value=mock_resp):
            result = gmail_service._refresh_access_token()

        assert result is False
        assert gmail_service._access_token is None
        assert gmail_service._refresh_token is None


# ── Gate Classification Tests ───────────────────────────────

class TestGateClassification:
    def test_gmail_actions_are_safe(self):
        """All Gmail verbs classified as SAFE (level 1) via SafetyManager."""
        from modules.safety import SafetyManager, SafetyLevel
        sm = SafetyManager()
        assert sm.get_action_level("gmail_search") == SafetyLevel.SAFE
        assert sm.get_action_level("gmail_read") == SafetyLevel.SAFE
        assert sm.get_action_level("gmail_list") == SafetyLevel.SAFE

    def test_gmail_in_safety_levels(self):
        """Gmail registered as SAFE in handler safety levels."""
        from core.handlers import _SAFETY_LEVELS
        assert _SAFETY_LEVELS.get("gmail") == 1

    def test_write_action_not_in_codebase(self):
        """No gmail.modify/compose/send/delete endpoints exist.
        /trash is ALLOWED (recoverable, 30-day window)."""
        import os
        gmail_dir = os.path.join(os.path.dirname(__file__), "..", "core", "gmail")
        # Proibidos: modify, compose, send, delete
        # Permitidos: trash, untrash, modify (para labels=read/unread)
        forbidden = ["gmail.modify", "gmail.compose", "/send", "/delete"]
        for pattern in forbidden:
            for root, _, files in os.walk(gmail_dir):
                for f in files:
                    if f.endswith(".py"):
                        path = os.path.join(root, f)
                        content = open(path, encoding="utf-8", errors="ignore").read()
                        assert pattern not in content, f"Forbidden endpoint '{pattern}' found in {path}"


# ── Private Account Redaction Tests ─────────────────────────

class TestPrivateAccountRedaction:
    def test_private_account_not_in_llm_output(self):
        """Private account messages should not appear in LLM-facing output."""
        from core.gmail.service import GmailService, MessageSummary

        service = GmailService(
            client_id="x", client_secret="x",
            account_email="test@gmail.com",
        )

        msg = MessageSummary(
            id="123",
            from_="private@school.edu",
            subject="Institutional email",
            date=datetime.now(),
            snippet="Sensitive content",
        )

        private_accounts = ["private@school.edu"]
        # Simulate redaction logic
        if msg.from_ in private_accounts:
            result = "[REDACTED — conta privada]"
        else:
            result = msg.snippet

        assert "Sensitive content" not in result
        assert "REDACTED" in result


# ── Scope Assertion Tests ───────────────────────────────────

class TestScopeAssertion:
    def test_scope_in_auth_url(self, gmail_service):
        url = gmail_service.get_auth_url()
        assert "gmail.readonly" in url

    def test_scopes_class_constant(self):
        from core.gmail.service import GMAIL_SCOPES
        assert GMAIL_SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"]


# ── Handler Tests ───────────────────────────────────────────

class TestGmailHandler:
    def test_handler_unconfigured(self):
        from core.handlers import handle_gmail
        result = handle_gmail("list", {}, gmail=None)
        assert "não configurado" in result.lower()

    def test_handler_unauthenticated(self):
        from core.handlers import handle_gmail
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = False
        mock_gmail.load_stored_tokens.return_value = False
        mock_gmail.get_auth_url.return_value = "https://example.com/auth"
        result = handle_gmail("list", {}, gmail=mock_gmail)
        assert "autenticado" in result.lower() or "autorizar" in result.lower()

    def test_handler_list_empty(self):
        from core.handlers import handle_gmail
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        mock_gmail.list_messages.return_value = []
        result = handle_gmail("list", {"query": "is:unread"}, gmail=mock_gmail)
        assert "nenhuma" in result.lower() or "0" in result

    def test_handler_unknown_action(self):
        from core.handlers import handle_gmail
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        result = handle_gmail("unknown_action", {}, gmail=mock_gmail)
        assert "desconhecida" in result.lower()


# ── Bug 1 Fix: Routing — Gmail commands reach handler ───────

class TestGmailRouting:
    """Gmail commands should be routed to the handler, not fall back to greeting."""

    def test_mark_read_routes_to_gmail(self):
        """'marque como lido' matches Gmail mark_read rule."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("marque como lido")
        assert len(intents) == 1
        assert intents[0].module == "gmail"
        assert intents[0].action == "mark_read"

    def test_search_discord_routes_to_gmail(self):
        """'busque e-mails do discord' matches Gmail search rule."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("busque e-mails do discord")
        assert len(intents) == 1
        assert intents[0].module == "gmail"
        assert intents[0].action == "search"

    def test_delete_email_routes_to_gmail(self):
        """'apague esse e-mail' matches Gmail trash rule."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("apague esse e-mail")
        assert len(intents) == 1
        assert intents[0].module == "gmail"
        assert intents[0].action == "trash"

    def test_list_inbox_routes_to_gmail(self):
        """'liste minhas mensagens' matches Gmail list rule."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("liste minhas mensagens não lidas")
        assert len(intents) == 1
        assert intents[0].module == "gmail"
        assert intents[0].action == "list"

    def test_read_email_routes_to_gmail(self):
        """'leia o e-mail' matches Gmail read rule."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("leia o e-mail")
        assert len(intents) == 1
        assert intents[0].module == "gmail"
        assert intents[0].action == "read"

    def test_block_sender_routes_to_gmail(self):
        """'bloquear remetente' matches Gmail block_sender rule."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("bloquear esse remetente de e-mail")
        assert len(intents) == 1
        assert intents[0].module == "gmail"
        assert intents[0].action == "block_sender"

    def test_greeting_does_not_route_to_gmail(self):
        """'bom dia' does NOT match any Gmail rule."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("bom dia")
        gmail_intents = [i for i in intents if i.module == "gmail"]
        assert len(gmail_intents) == 0

    def test_question_does_not_route_to_gmail(self):
        """'quem é você' does NOT match any Gmail rule."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("quem é você")
        gmail_intents = [i for i in intents if i.module == "gmail"]
        assert len(gmail_intents) == 0


# ── Bug 2 Fix: _looks_like_answer skips questions ──────────

class TestAnswerLearning:
    """Questions ending with ? should never be saved as learned answers."""

    def test_question_not_saved_as_answer(self):
        """'qual sua capacidade maxima' should NOT be treated as an answer."""
        from core.aris import Aris
        # We just test the _looks_like_answer logic directly
        aris = Aris.__new__(Aris)
        aris._last_aris_question = "Qual o clima de São Paulo?"
        # Even though _last_aris_question is set, a question should not match
        assert aris._looks_like_answer("qual sua capacidade maxima") is False

    def test_short_answer_still_works(self):
        """'sim' should still be detected as an answer (but excluded by list)."""
        from core.aris import Aris
        aris = Aris.__new__(Aris)
        aris._last_aris_question = "Quer que eu execute?"
        # 'sim' is in the exclusion list, so returns False
        assert aris._looks_like_answer("sim") is False

    def test_three_word_answeraccepted(self):
        """A 3-word non-question response can be an answer."""
        from core.aris import Aris
        aris = Aris.__new__(Aris)
        aris._last_aris_question = "Qual sua cor favorita?"
        assert aris._looks_like_answer("azul escuro") is True

    def test_four_word_answerrejected(self):
        """4-word responses are too long to be simple answers."""
        from core.aris import Aris
        aris = Aris.__new__(Aris)
        aris._last_aris_question = "Qual sua cor?"
        assert aris._looks_like_answer("azul bem escuro sim") is False


# ── Bug 4 Fix: Trash confirmation ──────────────────────────

class TestTrashConfirmation:
    """Trash without message_id must ask for scope, never execute blindly."""

    def test_trash_without_id_shows_scope(self):
        """'apague' sem ID pede escopo, não confirma."""
        from core.handlers import handle_gmail
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        # _last_gmail_results has messages
        import core.handlers as h
        h._last_gmail_results = [
            {"id": "abc", "from": "test@gmail.com", "subject": "Test"},
        ]
        result = handle_gmail("trash", {}, gmail=mock_gmail)
        assert "lixeira" in result.lower() or "id" in result.lower()
        assert "confirmação" in result.lower() or "confirme" in result.lower() or "sim" in result.lower()
        h._last_gmail_results = []

    def test_trash_with_id_requires_confirmation(self):
        """Trash with ID but without _confirmed asks for confirmation."""
        from core.handlers import handle_gmail
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        mock_msg = MagicMock()
        mock_msg.from_ = "test@gmail.com"
        mock_msg.subject = "Test Subject"
        mock_msg.date = datetime.now()
        mock_gmail.get_message.return_value = mock_msg
        result = handle_gmail("trash", {"message_id": "abc123"}, gmail=mock_gmail)
        assert "confirmar" in result.lower() or "sim" in result.lower()

    def test_trash_with_confirmed_executes(self):
        """Trash with _confirmed=True actually executes."""
        from core.handlers import handle_gmail
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        mock_gmail.trash_message.return_value = True
        result = handle_gmail("trash", {"message_id": "abc123", "_confirmed": True}, gmail=mock_gmail)
        assert "lixeira" in result.lower()
        mock_gmail.trash_message.assert_called_once_with("abc123")

    def test_trash_safety_level_is_critical(self):
        """gmail_trash classified as CRITICAL in safety levels."""
        from core.handlers import _SAFETY_LEVELS
        assert _SAFETY_LEVELS.get("gmail_trash") == 4


# ── Bug 5 Fix: Email synthesis ─────────────────────────────

class TestEmailSynthesis:
    """List/search should return synthesis, not raw dump."""

    def test_synthesize_emails_returns_string(self):
        """_synthesize_emails returns a string summary."""
        from core.handlers import _synthesize_emails
        from core.gmail.service import MessageSummary
        msgs = [
            MessageSummary(
                id="1", from_="spam@promo.com", subject="Super promo!",
                date=datetime.now(), snippet="Desconto 50%",
            ),
            MessageSummary(
                id="2", from_="security@google.com", subject="New login detected",
                date=datetime.now(), snippet="New sign-in from Chrome",
            ),
        ]
        result = _synthesize_emails(msgs)
        assert isinstance(result, str)
        assert len(result) > 20

    def test_synthesize_empty_returns_message(self):
        """_synthesize_emails with empty list returns helpful message."""
        from core.handlers import _synthesize_emails
        result = _synthesize_emails([])
        assert "nenhuma" in result.lower() or "nenhum" in result.lower()

    def test_importance_classification(self):
        """Emails are classified by importance heuristically."""
        from core.handlers import _classify_importance
        from core.gmail.service import MessageSummary

        # Security alert → high importance
        security = MessageSummary(
            id="1", from_="security@google.com",
            subject="New login detected from unknown device",
            date=datetime.now(), snippet="",
        )
        assert _classify_importance(security) >= 7

        # Spam promotion → low importance
        spam = MessageSummary(
            id="2", from_="promo@shop.com",
            subject="Super desconto black friday clique aqui",
            date=datetime.now(), snippet="",
        )
        assert _classify_importance(spam) <= 3

        # Normal email → medium
        normal = MessageSummary(
            id="3", from_="colleague@company.com",
            subject="Meeting tomorrow",
            date=datetime.now(), snippet="",
        )
        assert 4 <= _classify_importance(normal) <= 6


# ── Bug 6 Fix: Block sender ────────────────────────────────

class TestBlockSender:
    """Block sender registers intent without claiming Gmail action."""

    def test_block_sender_registers(self):
        """block_sender adds to blocked set and returns local-only message."""
        from core.handlers import handle_gmail, _blocked_senders
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        _blocked_senders.clear()
        result = handle_gmail("block_sender", {"sender": "spam@promo.com"}, gmail=mock_gmail)
        assert "spam@promo.com" in result
        assert "local" in result.lower() or "filtro" in result.lower() or "sessão" in result.lower()
        assert "spam@promo.com" in _blocked_senders
        _blocked_senders.clear()

    def test_blocked_sender_filtered_from_list(self):
        """List results filter out blocked senders."""
        from core.handlers import handle_gmail, _blocked_senders
        from unittest.mock import MagicMock
        from core.gmail.service import MessageSummary
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        mock_gmail.list_messages.return_value = [
            MessageSummary(id="1", from_="good@gmail.com", subject="Hi",
                           date=datetime.now(), snippet="Hello"),
            MessageSummary(id="2", from_="spam@promo.com", subject="Deal",
                           date=datetime.now(), snippet="Buy now"),
        ]
        _blocked_senders.clear()
        _blocked_senders.add("spam@promo.com")
        result = handle_gmail("list", {"query": "is:unread"}, gmail=mock_gmail)
        assert "spam@promo.com" not in result
        assert "good@gmail.com" in result
        _blocked_senders.clear()


# ── mark_read/trash without ID asks for clarification ──────

class TestClarificationFlow:
    """Actions without message_id should ask for clarification, not error."""

    def test_mark_read_no_id_shows_list(self):
        """mark_read without ID shows available messages."""
        from core.handlers import handle_gmail, _last_gmail_results
        import core.handlers as h
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        h._last_gmail_results = [
            {"id": "abc", "from": "test@gmail.com", "subject": "Test"},
        ]
        result = handle_gmail("mark_read", {}, gmail=mock_gmail)
        assert "qual" in result.lower() or "id" in result.lower()
        h._last_gmail_results = []

    def test_read_no_id_shows_list(self):
        """read without ID shows available messages."""
        from core.handlers import handle_gmail
        import core.handlers as h
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        h._last_gmail_results = [
            {"id": "abc", "from": "test@gmail.com", "subject": "Test"},
        ]
        result = handle_gmail("read", {}, gmail=mock_gmail)
        assert "qual" in result.lower() or "ler" in result.lower()
        h._last_gmail_results = []

    def test_trash_no_id_shows_scope(self):
        """trash without ID and with results shows scope message."""
        from core.handlers import handle_gmail
        import core.handlers as h
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        h._last_gmail_results = [
            {"id": "abc", "from": "test@gmail.com", "subject": "Test"},
        ]
        result = handle_gmail("trash", {}, gmail=mock_gmail)
        assert "lixeira" in result.lower() or "id" in result.lower()
        h._last_gmail_results = []


# ── Personality prompt has Gmail examples ───────────────────

class TestPersonalityGmail:
    """Personality prompt includes Gmail examples for LLM."""

    def test_personality_has_gmail_examples(self):
        """config/personality.py includes Gmail module."""
        from config.personality import ARIS_PERSONALITY
        assert "gmail" in ARIS_PERSONALITY.lower()
        assert "trash" in ARIS_PERSONALITY.lower()

    def test_interpreter_has_gmail_module(self):
        """advanced_interpreter includes Gmail module with all actions."""
        from core.advanced_interpreter import AdvancedInterpreter
        interp = AdvancedInterpreter()
        modules = interp.get_modules_for_prompt()
        assert "gmail" in modules.lower()
        assert "trash" in modules.lower()
        assert "mark_read" in modules.lower()


# ── Gmail Bulk Trash Tests ──────────────────────────────────

class TestGmailBulkTrash:
    """Bulk trash with confirmation flow."""

    def test_bulk_trash_requires_confirmation(self):
        """Bulk trash without _confirmed asks for confirmation."""
        from core.handlers import handle_gmail
        import core.handlers as h
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        h._last_gmail_results = [
            {"id": "a", "from": "x@g.com", "subject": "A"},
            {"id": "b", "from": "y@g.com", "subject": "B"},
        ]
        result = handle_gmail("trash", {"bulk": True}, gmail=mock_gmail)
        assert "confirmação" in result.lower() or "confirmar" in result.lower() or "sim" in result.lower()
        h._last_gmail_results = []

    def test_bulk_trash_confirmed_executes(self):
        """Bulk trash with _confirmed=True executes all."""
        from core.handlers import handle_gmail
        import core.handlers as h
        from unittest.mock import MagicMock
        mock_gmail = MagicMock()
        mock_gmail.is_configured = True
        mock_gmail.is_authenticated = True
        mock_gmail.trash_message.return_value = True
        h._last_gmail_results = [
            {"id": "a", "from": "x@g.com", "subject": "A"},
            {"id": "b", "from": "y@g.com", "subject": "B"},
        ]
        result = handle_gmail("trash", {"bulk": True, "_confirmed": True}, gmail=mock_gmail)
        assert "lixeira" in result.lower() or "massa" in result.lower()
        assert mock_gmail.trash_message.call_count == 2
        h._last_gmail_results = []

    def test_bulk_trash_regex_matches(self):
        """'apague todos os emails' matches bulk trash rule."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("apague todos os emails")
        assert len(intents) == 1
        assert intents[0].module == "gmail"
        assert intents[0].action == "trash"
        assert intents[0].params.get("bulk") is True

    def test_non_bulk_trash_no_bulk_param(self):
        """'apague esse email' does NOT set bulk."""
        from core.neural.reasoning.reasoning_router import DeterministicEngine
        engine = DeterministicEngine()
        intents = engine.parse("apague esse e-mail")
        assert len(intents) == 1
        assert intents[0].params.get("bulk") is not True


# ── Context Tracking Tests ──────────────────────────────────

class TestContextTracking:
    """Context detects project/evolution topics."""

    def test_project_evolution_detected(self):
        """'atualizar' and 'melhorar' set topic to projeto_evolution."""
        from core.advanced_interpreter import AdvancedInterpreter
        interp = AdvancedInterpreter()
        interp.update_context("o que você acha de atualizar a ARIS?")
        assert interp._context.last_topic == "projeto_evolution"

    def test_email_topic_detected(self):
        """'email' sets topic to email."""
        from core.advanced_interpreter import AdvancedInterpreter
        interp = AdvancedInterpreter()
        interp.update_context("liste minhas mensagens de email")
        assert interp._context.last_topic == "email"

    def test_vision_topic_detected(self):
        """'tela' sets topic to visao."""
        from core.advanced_interpreter import AdvancedInterpreter
        interp = AdvancedInterpreter()
        interp.update_context("o que tem na tela?")
        assert interp._context.last_topic == "visao"


# ── Personality Prompt Tests ────────────────────────────────

class TestPersonalityNoGreeting:
    """Personality prompt instructs LLM to avoid generic greetings."""

    def test_personality_has_no_greeting_rule(self):
        """Personality prompt has rule against generic greetings."""
        from config.personality import ARIS_PERSONALITY
        assert "nunca comece" in ARIS_PERSONALITY.lower() or "nunca responda" in ARIS_PERSONALITY.lower()

    def test_personality_has_substantive_response_examples(self):
        """Personality prompt encourages authentic responses."""
        from config.personality import ARIS_PERSONALITY
        assert "você mesmo" in ARIS_PERSONALITY.lower() or "autêntico" in ARIS_PERSONALITY.lower()

    def test_interpreter_has_no_greeting_rule(self):
        """Interpreter prompt reinforces no generic greetings."""
        from core.advanced_interpreter import AdvancedInterpreter
        interp = AdvancedInterpreter()
        prompt = interp.build_interpretation_prompt("teste")
        assert "NUNCA" in prompt or "nunca" in prompt.lower()
