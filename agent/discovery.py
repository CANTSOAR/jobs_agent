from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

from evaluator.relevance import evaluate_jobs
from inbox import gmail_is_configured, poll_gmail
from ingestion.service import sync_simplify_feed
from notifications.notifier import send_alerts


def create_supabase_client() -> Client:
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required")
    return create_client(url, key)


def ingest_sources(supabase: Client) -> dict[str, Any]:
    gmail_result = None
    if gmail_is_configured():
        try:
            gmail_result = poll_gmail(supabase)
            print(
                "Gmail: "
                f"{gmail_result.messages_seen} seen, "
                f"{gmail_result.messages_inserted} new, "
                f"{gmail_result.digest_listings} digest listing(s)."
            )
        except Exception as exc:
            # Gmail is an optional trigger/reconciliation source. The structured
            # feed remains authoritative and should still run if OAuth expires.
            print(f"Gmail ingestion failed; continuing with structured feed: {exc}")

    sync_result = sync_simplify_feed(supabase)
    print(
        "Simplify feed: "
        f"status={sync_result['status']} "
        f"seen={sync_result['records_seen']} "
        f"inserted={sync_result['jobs_inserted']} "
        f"updated={sync_result['jobs_updated']}"
    )
    return {"gmail": gmail_result, "simplify": sync_result}


def run_discovery(supabase: Client | None = None) -> dict[str, Any]:
    """Fast path for frequent polling: ingest, match, queue, and notify."""
    client = supabase or create_supabase_client()
    result = ingest_sources(client)

    if os.environ.get("DEEPSEEK_API_KEY"):
        print("Evaluating newly discovered jobs...")
        evaluate_jobs(client)
    else:
        print("DEEPSEEK_API_KEY is absent; skipping relevance evaluation.")

    print("Sending any pending notification digest...")
    send_alerts(client)
    return result


def main() -> int:
    run_discovery()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
