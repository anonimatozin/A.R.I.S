"""Gmail integration for A.R.I.S. — read-only."""

from core.gmail.service import (
    GmailService,
    MessageSummary,
    MessageDetail,
    GMAIL_SCOPES,
)
from core.gmail.manager import (
    GmailManager,
    GmailAccountConfig,
    AccountStatus,
)

__all__ = [
    "GmailService",
    "MessageSummary",
    "MessageDetail",
    "GMAIL_SCOPES",
    "GmailManager",
    "GmailAccountConfig",
    "AccountStatus",
]
