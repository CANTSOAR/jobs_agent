from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

from .repository import SupabaseApplicationRepository
from .runner import ApplicationRunner


def _path(value: str | None) -> Path | None:
    return Path(value).expanduser().resolve() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claim and safely inspect/autofill one queued job application."
    )
    parser.add_argument(
        "--worker-id",
        default=f"local-{socket.gethostname()}",
        help="Lease owner recorded in Supabase.",
    )
    parser.add_argument("--lease-minutes", type=int, default=30)
    parser.add_argument(
        "--resume",
        default=os.environ.get("APPLICATION_RESUME_PATH"),
        help="Local resume PDF path; never uploaded to the database by this command.",
    )
    parser.add_argument(
        "--browser-profile-dir",
        default=os.environ.get("APPLICATION_BROWSER_PROFILE_DIR"),
        help="Dedicated Chromium profile directory (do not use your normal Chrome profile).",
    )
    parser.add_argument(
        "--artifact-dir",
        default=os.environ.get("APPLICATION_ARTIFACT_DIR"),
        help="Optional private directory for review screenshots.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without a visible browser. Headed mode is the safe default.",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Restrict all browser targets to loopback HTTP mock servers.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep polling the queue. Without this flag, process at most one item.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=60,
        help="Queue polling interval in watch mode (minimum 10 seconds).",
    )
    return parser


def _print_result(result) -> int:
    if result is None:
        print(json.dumps({"status": "idle", "message": "No queued applications"}))
        return 0
    print(
        json.dumps(
            {
                "application_id": result.application_id,
                "status": result.status.value,
                "adapter": result.adapter,
                "form_fingerprint": result.form_fingerprint,
                "blockers": list(result.blockers),
                "confirmation_id": result.receipt.confirmation_id if result.receipt else None,
            },
            sort_keys=True,
        )
    )
    return 0 if result.status.value not in {"failed", "submission_unknown"} else 1


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY are required")

    repository = SupabaseApplicationRepository(
        create_client(url, key),
        resume_path=_path(args.resume),
    )
    runner = ApplicationRunner(
        repository,
        test_mode=args.test_mode,
        headless=args.headless,
        user_data_dir=_path(args.browser_profile_dir),
        artifact_dir=_path(args.artifact_dir),
    )
    if not args.watch:
        return _print_result(runner.run_next(args.worker_id, args.lease_minutes))

    poll_seconds = max(10, args.poll_seconds)
    print(json.dumps({"status": "watching", "poll_seconds": poll_seconds}))
    try:
        while True:
            result = runner.run_next(args.worker_id, args.lease_minutes)
            _print_result(result)
            if result is None:
                time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped"}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
