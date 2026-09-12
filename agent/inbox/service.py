from __future__ import annotations

import os
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .gmail import GmailCredentials, get_message, list_message_ids, refresh_access_token
from .parser import PARSER_VERSION, classify_message, parse_swelist_html, parse_swelist_text


DEFAULT_QUERY = "from:noreply@swelist.com newer_than:7d"


@dataclass(frozen=True)
class PollResult:
    messages_seen: int = 0
    messages_inserted: int = 0
    digest_messages: int = 0
    digest_listings: int = 0


def gmail_is_configured() -> bool:
    return all(os.environ.get(name) for name in (
        "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
    ))


def _configured_credentials() -> GmailCredentials:
    if not gmail_is_configured():
        raise RuntimeError(
            "Gmail ingestion requires GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN"
        )
    return GmailCredentials(
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
    )


def _resolve_user_id(supabase) -> str | None:
    explicit = os.environ.get("GMAIL_OWNER_USER_ID")
    if explicit:
        return explicit
    profiles = supabase.table("profiles").select("id").limit(2).execute().data
    return profiles[0]["id"] if len(profiles) == 1 else None


def poll_gmail(supabase) -> PollResult:
    """Idempotently copy matching Gmail messages into `inbound_messages`.

    Discovery still comes from the structured Simplify feed. A new SWEList digest
    is a fast trigger and reconciliation signal, while the durable inbox can later
    drive application status updates.
    """
    if not gmail_is_configured():
        return PollResult()

    token = refresh_access_token(_configured_credentials())
    query = os.environ.get("GMAIL_INGEST_QUERY", DEFAULT_QUERY)
    max_results = max(1, min(int(os.environ.get("GMAIL_MAX_RESULTS", "50")), 500))
    owner_id = _resolve_user_id(supabase)

    seen_count = inserted_count = digest_count = listing_count = 0
    for message_id in list_message_ids(token, query=query, max_results=max_results):
        seen_count += 1
        existing = (
            supabase.table("inbound_messages")
            .select("id")
            .eq("provider", "gmail")
            .eq("provider_message_id", message_id)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            continue

        message = get_message(token, message_id)
        display_text = message.text
        if not display_text and message.html:
            display_text = BeautifulSoup(message.html, "html.parser").get_text("\n")
        message_type = classify_message(message.sender, message.subject, display_text)
        listings = []
        if message_type == "swelist_digest":
            listings = parse_swelist_html(message.html) if message.html else parse_swelist_text(display_text)
            digest_count += 1
            listing_count += len(listings)

        store_raw = os.environ.get("GMAIL_STORE_RAW_BODY", "false").casefold() == "true"
        supabase.table("inbound_messages").insert({
            "user_id": owner_id,
            "provider": "gmail",
            "provider_message_id": message.message_id,
            "sender": message.sender,
            "recipients": list(message.recipients),
            "subject": message.subject,
            "received_at": message.received_at,
            "message_type": message_type,
            "parser_version": PARSER_VERSION if message_type == "swelist_digest" else "classifier-v1",
            "status": "parsed",
            "metadata": {
                "thread_id": message.thread_id,
                "label_ids": list(message.label_ids),
                "listing_count": len(listings),
                "listings": [listing.to_dict() for listing in listings],
            },
            "raw_body": (message.html or message.text) if store_raw else None,
        }).execute()
        inserted_count += 1

    return PollResult(
        messages_seen=seen_count,
        messages_inserted=inserted_count,
        digest_messages=digest_count,
        digest_listings=listing_count,
    )
