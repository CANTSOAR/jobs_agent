from __future__ import annotations

import os

from dotenv import load_dotenv
from supabase import create_client

from .service import gmail_is_configured, poll_gmail


def main() -> int:
    load_dotenv()
    if not gmail_is_configured():
        print("Gmail ingestion is not configured; see .env.example.")
        return 2
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    result = poll_gmail(supabase)
    print(
        "Gmail poll complete: "
        f"{result.messages_seen} seen, {result.messages_inserted} new, "
        f"{result.digest_listings} digest listings."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
