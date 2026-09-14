"""Gmail integration for A.R.I.S. — read-only."""

from core.gmail.service import (
    GmailService,
    MessageSummary,
    MessageDetail,
    GMAIL_SCOPES,
)

__all__ = [
    "GmailService",
    "MessageSummary",
    "MessageDetail",
    "GMAIL_SCOPES",
]
