import os
import smtplib
from email.mime.text import MIMEText

import httpx

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")

NOTIFY_THRESHOLD = 70


def _send_ntfy(title: str, message: str):
    if not NTFY_TOPIC or NTFY_TOPIC == "your-ntfy-topic":
        return
    httpx.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        content=message.encode("utf-8"),
        headers={"Title": title},
        timeout=10,
    )


def _send_email(to_email: str, subject: str, body: str):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS or SMTP_HOST == "smtp.example.com":
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def send_alerts(supabase):
    """
    Notifies on job matches scored at or above NOTIFY_THRESHOLD that haven't been
    notified yet, then marks them 'notified' so they aren't sent twice. Both ntfy and
    SMTP are no-ops until their env vars are filled in with real values.
    """
    matches = (
        supabase.table("user_job_matches")
        .select("id, user_id, score, reasoning, jobs(title, url, location, companies(name))")
        .eq("status", "new")
        .gte("score", NOTIFY_THRESHOLD)
        .execute()
        .data
    )

    for match in matches:
        job = match.get("jobs") or {}
        company = job.get("companies") or {}
        title = f"{job.get('title', 'New job')} at {company.get('name', 'a company')}"
        body = f"Score: {match['score']}/100\n{match.get('reasoning') or ''}\n{job.get('url') or ''}"

        print(f"Sending alert for job match ID: {match['id']}")
        _send_ntfy(title, body)

        try:
            profile = (
                supabase.table("profiles")
                .select("email_notifications_enabled")
                .eq("id", match["user_id"])
                .single()
                .execute()
                .data
            )
            email_enabled = (profile or {}).get("email_notifications_enabled", True)

            if email_enabled:
                user = supabase.auth.admin.get_user_by_id(match["user_id"])
                email = user.user.email if user and user.user else None
                if email:
                    _send_email(email, title, body)
        except Exception as exc:
            print(f"  Could not look up user email: {exc}")

        supabase.table("user_job_matches").update({"status": "notified"}).eq("id", match["id"]).execute()
