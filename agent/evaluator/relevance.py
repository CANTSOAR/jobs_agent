import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

from ingestion.normalize import normalize_company_name
from llm import get_client

MATCH_PROMPT = """A job seeker has the following resume, goals, and structured job
preferences. Score how well the job matches what they are looking for, from 0-100
(100 = perfect match, 0 = completely irrelevant). Do not infer or invent facts about
the candidate.

Resume:
---
{resume_text}
---

Goals:
---
{goal_description}
---

Job preferences:
---
{job_preferences}
---

Job:
Title: {job_title}
Company: {company_name}
Location: {location}
Category: {category}
Terms: {terms}
Sponsorship signal: {sponsorship}
Degree signal: {degrees}

Respond with ONLY valid JSON: {{"score": <integer 0-100>, "reasoning": "<one or two sentences>"}}
"""

PAGE_SIZE = 1000


def _fetch_all(query, page_size: int = PAGE_SIZE) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = query.range(offset, offset + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().lower() for item in value if str(item).strip()]


def passes_job_preferences(job: dict[str, Any], preferences: dict[str, Any] | None) -> bool:
    """Apply only explicit hard gates before spending an LLM call.

    Unknown/missing upstream data passes a gate rather than risking a false rejection.
    Soft preferences remain in the LLM prompt.
    """
    preferences = preferences if isinstance(preferences, dict) else {}
    title = str(job.get("title") or "").lower()
    location = str(job.get("location") or "").lower()

    excluded_keywords = _string_list(preferences.get("excluded_title_keywords"))
    if any(keyword in title for keyword in excluded_keywords):
        return False

    target_terms = _string_list(preferences.get("target_terms"))
    job_terms = set(_string_list(job.get("terms")))
    if target_terms and not any(
        term in title or term in job_terms
        for term in target_terms
    ):
        return False

    allowed_categories = set(_string_list(preferences.get("target_categories")))
    category = str(job.get("category") or "").strip().lower()
    if allowed_categories and category and category not in allowed_categories:
        return False

    is_remote = "remote" in location
    if preferences.get("allow_remote") is False and is_remote:
        return False

    preferred_locations = _string_list(preferences.get("preferred_locations"))
    if (
        preferred_locations
        and location
        and not preferences.get("willing_to_relocate", False)
        and not (is_remote and preferences.get("allow_remote", True))
        and not any(item in location for item in preferred_locations)
    ):
        return False

    return True


def _recent_enough(job: dict[str, Any], lookback_days: int) -> bool:
    """Bound feed evaluation cost while retaining undated subscribed-company jobs."""
    if job.get("discovery_method") not in {"feed", "mixed"}:
        return True
    raw = job.get("posted_at")
    if not raw:
        return False
    try:
        posted_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return posted_at >= datetime.now(timezone.utc) - timedelta(days=lookback_days)


def _score_job(job: dict, company_name: str, profile: dict) -> dict:
    response = get_client().chat.completions.create(
        model="deepseek-chat",
        messages=[{
            "role": "user",
            "content": MATCH_PROMPT.format(
                resume_text=profile.get("resume_text") or "(not provided)",
                goal_description=profile.get("goal_description") or "(not provided)",
                job_preferences=json.dumps(profile.get("job_preferences") or {}, sort_keys=True),
                job_title=job["title"],
                company_name=company_name,
                location=job.get("location") or "unspecified",
                category=job.get("category") or "unspecified",
                terms=", ".join(job.get("terms") or []) or "unspecified",
                sponsorship=job.get("sponsorship") or "unspecified",
                degrees=", ".join(job.get("degrees") or []) or "unspecified",
            ),
        }],
        response_format={"type": "json_object"},
    )
    result = json.loads(response.choices[0].message.content)
    result["score"] = max(0, min(100, int(result.get("score", 0))))
    return result


def _first(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        return data[0] if data else None
    return data if isinstance(data, dict) else None


def _queue_application_if_allowed(
    supabase,
    *,
    job: dict[str, Any],
    user_id: str,
    match_id: str | None,
    score: int,
    policy: dict[str, Any] | None,
) -> None:
    if not policy or score < int(policy.get("min_match_score", 80)):
        return
    if not job.get("url"):
        return
    mode = policy.get("default_mode", "track_only")
    if mode == "track_only":
        return

    allowlist = {
        normalize_company_name(item)
        for item in policy.get("company_allowlist") or []
        if isinstance(item, str) and item.strip()
    }
    company_name = str((job.get("companies") or {}).get("name") or "")
    if allowlist and normalize_company_name(company_name) not in allowlist:
        return

    payload = {
        "user_id": user_id,
        "job_id": job["id"],
        "match_id": match_id,
        "status": "queued",
        "mode": mode,
        "target_url": job.get("url"),
        "application_url": job.get("url"),
        # Broad automatic-submit consent lives in application_policies. This field
        # is reserved for a short-lived, exact-fingerprint per-application review.
        "submission_authorized_at": None,
    }
    # Never reset a submitted or in-progress row to queued during re-evaluation.
    supabase.table("applications").upsert(
        payload,
        on_conflict="user_id,job_id",
        ignore_duplicates=True,
    ).execute()


def evaluate_jobs(supabase):
    """Score subscribed-company and opted-in feed jobs, then safely queue matches."""
    profiles = _fetch_all(
        supabase.table("profiles").select(
            "id, resume_text, goal_description, job_preferences, feed_discovery_enabled"
        )
    )
    profiles = [
        profile
        for profile in profiles
        if profile.get("resume_text") or profile.get("goal_description")
    ]
    if not profiles:
        return

    profiles_by_id = {profile["id"]: profile for profile in profiles}
    user_ids = list(profiles_by_id)
    subscriptions = _fetch_all(
        supabase.table("user_company_subscriptions").select("user_id, company_id")
    )
    users_by_company: dict[str, set[str]] = {}
    for subscription in subscriptions:
        if subscription["user_id"] in profiles_by_id:
            users_by_company.setdefault(subscription["company_id"], set()).add(subscription["user_id"])

    jobs = _fetch_all(
        supabase.table("jobs")
        .select(
            "id, company_id, title, url, location, category, terms, sponsorship, degrees, "
            "posted_at, discovery_method, companies(name)"
        )
        .eq("is_active", True)
        .order("posted_at", desc=True, nullsfirst=False)
    )
    if not jobs:
        return

    lookback_days = max(1, min(int(os.environ.get("FEED_EVALUATION_LOOKBACK_DAYS", "14")), 365))
    jobs = [job for job in jobs if _recent_enough(job, lookback_days)]
    if not jobs:
        return

    job_ids = [job["id"] for job in jobs]
    existing_pairs: set[tuple[str, str]] = set()
    for offset in range(0, len(job_ids), 200):
        rows = _fetch_all(
            supabase.table("user_job_matches")
            .select("user_id, job_id")
            .in_("job_id", job_ids[offset : offset + 200])
        )
        existing_pairs.update((row["user_id"], row["job_id"]) for row in rows)

    policies = _fetch_all(
        supabase.table("application_policies").select("*").in_("user_id", user_ids)
    )
    policies_by_user = {policy["user_id"]: policy for policy in policies}

    pending: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    for job in jobs:
        candidate_users = set(users_by_company.get(job["company_id"], set()))
        if job.get("discovery_method") in {"feed", "mixed"}:
            candidate_users.update(
                user_id
                for user_id, profile in profiles_by_id.items()
                if profile.get("feed_discovery_enabled", True)
            )

        for user_id in candidate_users:
            if (user_id, job["id"]) in existing_pairs:
                continue
            profile = profiles_by_id[user_id]
            if not passes_job_preferences(job, profile.get("job_preferences")):
                continue
            pending.append((job, user_id, profile))

    if not pending:
        return

    max_evaluations = max(0, int(os.environ.get("MAX_NEW_JOB_EVALUATIONS", "200")))
    if max_evaluations == 0:
        print("  Job evaluation is disabled by MAX_NEW_JOB_EVALUATIONS=0.")
        return
    pending = pending[:max_evaluations]
    max_workers = max(1, min(int(os.environ.get("JOB_EVALUATION_WORKERS", "8")), 16))
    print(f"  Scoring {len(pending)} job/user pair(s) ({max_workers} at a time)...")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _score_job,
                job,
                str((job.get("companies") or {}).get("name") or ""),
                profile,
            ): (job, user_id)
            for job, user_id, profile in pending
        }

        for future in as_completed(futures):
            job, user_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                print(f"  Relevance evaluation failed for job {job['id']} / user {user_id}: {exc}")
                continue

            match_result = supabase.table("user_job_matches").upsert(
                {
                    "user_id": user_id,
                    "job_id": job["id"],
                    "score": result["score"],
                    "reasoning": result.get("reasoning"),
                },
                on_conflict="user_id,job_id",
            ).execute()
            match = _first(match_result.data)
            try:
                _queue_application_if_allowed(
                    supabase,
                    job=job,
                    user_id=user_id,
                    match_id=match.get("id") if match else None,
                    score=result["score"],
                    policy=policies_by_user.get(user_id),
                )
            except Exception as exc:
                print(f"  Could not queue application for job {job['id']} / user {user_id}: {exc}")
