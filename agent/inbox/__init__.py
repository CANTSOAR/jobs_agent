"""Mailbox ingestion for job digests and application lifecycle messages."""

from .service import gmail_is_configured, poll_gmail

__all__ = ["gmail_is_configured", "poll_gmail"]
