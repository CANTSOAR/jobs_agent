import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import Client, create_client

from main import evaluate_and_notify, run_agent

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def poll_and_run():
    """
    Meant to be run on a tight cron interval (e.g. every few minutes). It's a single
    cheap query unless a whitelisted user has requested an on-demand run, in which
    case it runs the same full pipeline as the scheduled job.
    """
    pending = supabase.table("run_requests").select("id, request_type").eq("status", "pending").execute().data
    if not pending:
        return

    request_ids = [row["id"] for row in pending]
    supabase.table("run_requests").update({"status": "running"}).in_("id", request_ids).execute()

    # A 'full' request (the regular "Run Agent Now" button) takes priority over any
    # 'evaluate_only' requests batched in alongside it, since it covers them anyway.
    needs_full_run = any(row.get("request_type", "full") == "full" for row in pending)

    try:
        if needs_full_run:
            run_agent()
        else:
            evaluate_and_notify()
    except Exception:
        supabase.table("run_requests").update({"status": "failed"}).in_("id", request_ids).execute()
        raise

    supabase.table("run_requests").update({
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).in_("id", request_ids).execute()


if __name__ == "__main__":
    poll_and_run()
