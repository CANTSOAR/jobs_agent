import os
import smtplib
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _send_email(to_email: str, subject: str, body: str) -> bool:
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    if not smtp_host or not smtp_user or not smtp_pass or smtp_host == "smtp.example.com":
        return False
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if os.environ.get("SMTP_USE_STARTTLS", "true").casefold() == "true":
            server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
    return True


def _threshold(profile: dict[str, Any]) -> int:
    default = _bounded_int_env("NOTIFY_MATCH_THRESHOLD", 70, 0, 100)
    preferences = profile.get("job_preferences")
    if not isinstance(preferences, dict) or "min_match_score" not in preferences:
        return default
    try:
        return max(0, min(int(preferences["min_match_score"]), 100))
    except (TypeError, ValueError):
        return default


def _notification_cutoff(now: datetime) -> str:
    lookback_days = _bounded_int_env("NOTIFICATION_LOOKBACK_DAYS", 2, 1, 30)
    return (now - timedelta(days=lookback_days)).isoformat()


def _digest_due(profile: dict[str, Any], now: datetime) -> bool:
    raw = profile.get("last_job_digest_at")
    if not raw:
        return True
    try:
        last_digest = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    if last_digest.tzinfo is None:
        last_digest = last_digest.replace(tzinfo=timezone.utc)
    interval = timedelta(
        minutes=_bounded_int_env("NOTIFICATION_MIN_INTERVAL_MINUTES", 240, 15, 1440)
    )
    return now - last_digest >= interval


def _retry_write(operation, attempts: int = 3):
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def _digest_body(matches: list[dict[str, Any]]) -> str:
    lines = [f"{len(matches)} new job match(es):", ""]
    for match in sorted(matches, key=lambda item: int(item["score"]), reverse=True):
        job = match.get("jobs") or {}
        company = job.get("companies") or {}
        lines.extend(
            [
                f"{match['score']}/100 — {job.get('title', 'New job')} at {company.get('name', 'a company')}",
                str(job.get("location") or "Location not specified"),
                str(match.get("reasoning") or ""),
                str(job.get("url") or ""),
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def send_alerts(supabase):
    """
    Send one digest per user, then mark only successfully delivered matches. Missing
    SMTP configuration and delivery failures intentionally leave rows as `new`.
    """
    now = datetime.now(timezone.utc)
    matches = (
        supabase.table("user_job_matches")
        .select(
            "id, user_id, score, reasoning, created_at, "
            "jobs(title, url, location, companies(name))"
        )
        .eq("status", "new")
        .gte("created_at", _notification_cutoff(now))
        .order("created_at", desc=True)
        .execute()
        .data
    )

    matches_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in matches or []:
        matches_by_user[match["user_id"]].append(match)

    for user_id, user_matches in matches_by_user.items():
        try:
            profile = (
                supabase.table("profiles")
                .select(
                    "email_notifications_enabled, job_preferences, last_job_digest_at"
                )
                .eq("id", user_id)
                .single()
                .execute()
                .data
            ) or {}
            if not profile.get("email_notifications_enabled", True):
                continue
            if not _digest_due(profile, now):
                continue

            threshold = _threshold(profile)
            eligible = sorted(
                (match for match in user_matches if int(match["score"]) >= threshold),
                key=lambda item: int(item["score"]),
                reverse=True,
            )[: _bounded_int_env("NOTIFICATION_MAX_MATCHES", 50, 1, 100)]
            if not eligible:
                continue

            user = supabase.auth.admin.get_user_by_id(user_id)
            email = user.user.email if user and user.user else None
            if not email:
                print("  No notification address found; leaving matches new.")
                continue

            subject = f"{len(eligible)} new job match{'es' if len(eligible) != 1 else ''}"
            if not _send_email(email, subject, _digest_body(eligible)):
                print("  SMTP is not configured; leaving job matches new.")
                continue

            match_ids = [match["id"] for match in eligible]
            _retry_write(
                lambda: supabase.table("user_job_matches")
                .update({"status": "notified"})
                .in_("id", match_ids)
                .execute()
            )
            _retry_write(
                lambda: supabase.table("profiles")
                .update({"last_job_digest_at": now.isoformat()})
                .eq("id", user_id)
                .execute()
            )
            print(f"  Sent a digest with {len(match_ids)} match(es).")
        except Exception as exc:
            print(f"  Could not deliver a notification digest: {exc}")
