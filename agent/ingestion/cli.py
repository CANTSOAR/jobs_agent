import os

from dotenv import load_dotenv
from supabase import create_client

from ingestion.service import sync_simplify_feed


def main() -> None:
    load_dotenv()
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY are required")

    result = sync_simplify_feed(create_client(supabase_url, supabase_key))
    print(
        "Simplify sync: "
        f"status={result['status']} "
        f"seen={result['records_seen']} "
        f"inserted={result['jobs_inserted']} "
        f"updated={result['jobs_updated']}"
    )


if __name__ == "__main__":
    main()
