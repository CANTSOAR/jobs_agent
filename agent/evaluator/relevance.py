import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm import get_client

MATCH_PROMPT = """A job seeker has the following resume and goals. Score how well the
job below matches what they're looking for, from 0-100 (100 = perfect match, 0 =
completely irrelevant).

Resume:
---
{resume_text}
---

Goals:
---
{goal_description}
---

Job:
Title: {job_title}
Company: {company_name}
Location: {location}

Respond with ONLY valid JSON: {{"score": <integer 0-100>, "reasoning": "<one or two sentences>"}}
"""

# DeepSeek calls are network-bound (~2-3s each), so a thread pool gets a meaningful
# speedup scoring many jobs. Kept modest to avoid hitting API rate limits.
MAX_WORKERS = 8


def _score_job(job: dict, company_name: str, profile: dict) -> dict:
    response = get_client().chat.completions.create(
        model="deepseek-chat",
        messages=[{
            "role": "user",
            "content": MATCH_PROMPT.format(
                resume_text=profile.get("resume_text") or "(not provided)",
                goal_description=profile.get("goal_description") or "(not provided)",
                job_title=job["title"],
                company_name=company_name,
                location=job.get("location") or "unspecified",
            ),
        }],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def evaluate_jobs(supabase):
    """
    Scores every job against every user subscribed to that job's company, skipping
    pairs that have already been scored. Requires the user to have saved a resume or
    goal description on their profile.
    """
    subscriptions = supabase.table("user_company_subscriptions").select("user_id, company_id").execute().data

    users_by_company: dict[str, list[str]] = {}
    for sub in subscriptions:
        users_by_company.setdefault(sub["company_id"], []).append(sub["user_id"])

    if not users_by_company:
        return

    company_ids = list(users_by_company.keys())

    jobs = supabase.table("jobs").select("*").in_("company_id", company_ids).execute().data
    if not jobs:
        return

    companies = supabase.table("companies").select("id, name").in_("id", company_ids).execute().data
    company_names = {c["id"]: c["name"] for c in companies}

    job_ids = [job["id"] for job in jobs]
    existing_pairs = {
        (row["user_id"], row["job_id"])
        for row in supabase.table("user_job_matches").select("user_id, job_id").in_("job_id", job_ids).execute().data
    }

    user_ids = {user_id for users in users_by_company.values() for user_id in users}
    profiles = supabase.table("profiles").select("id, resume_text, goal_description").in_("id", list(user_ids)).execute().data
    profiles_by_id = {p["id"]: p for p in profiles}

    pending = []
    for job in jobs:
        for user_id in users_by_company.get(job["company_id"], []):
            if (user_id, job["id"]) in existing_pairs:
                continue

            profile = profiles_by_id.get(user_id) or {}
            if not profile.get("resume_text") and not profile.get("goal_description"):
                continue

            pending.append((job, user_id, profile))

    if not pending:
        return

    print(f"  Scoring {len(pending)} job/user pair(s) ({MAX_WORKERS} at a time)...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_score_job, job, company_names.get(job["company_id"], ""), profile): (job, user_id)
            for job, user_id, profile in pending
        }

        for future in as_completed(futures):
            job, user_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                print(f"  Relevance evaluation failed for job {job['id']} / user {user_id}: {exc}")
                continue

            supabase.table("user_job_matches").insert({
                "user_id": user_id,
                "job_id": job["id"],
                "score": int(result.get("score", 0)),
                "reasoning": result.get("reasoning"),
            }).execute()
