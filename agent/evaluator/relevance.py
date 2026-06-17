import json
import os

from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
)

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

    jobs = (
        supabase.table("jobs")
        .select("*")
        .in_("company_id", list(users_by_company.keys()))
        .execute()
        .data
    )

    company_names: dict[str, str] = {}
    profiles_cache: dict[str, dict] = {}

    for job in jobs:
        if job["company_id"] not in company_names:
            company = supabase.table("companies").select("name").eq("id", job["company_id"]).single().execute().data
            company_names[job["company_id"]] = company["name"] if company else ""

        for user_id in users_by_company.get(job["company_id"], []):
            existing = (
                supabase.table("user_job_matches")
                .select("id")
                .eq("user_id", user_id)
                .eq("job_id", job["id"])
                .execute()
                .data
            )
            if existing:
                continue

            if user_id not in profiles_cache:
                profiles_cache[user_id] = (
                    supabase.table("profiles")
                    .select("resume_text, goal_description")
                    .eq("id", user_id)
                    .single()
                    .execute()
                    .data
                ) or {}

            profile = profiles_cache[user_id]
            if not profile.get("resume_text") and not profile.get("goal_description"):
                continue

            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{
                        "role": "user",
                        "content": MATCH_PROMPT.format(
                            resume_text=profile.get("resume_text") or "(not provided)",
                            goal_description=profile.get("goal_description") or "(not provided)",
                            job_title=job["title"],
                            company_name=company_names[job["company_id"]],
                            location=job.get("location") or "unspecified",
                        ),
                    }],
                    response_format={"type": "json_object"},
                )
                result = json.loads(response.choices[0].message.content)
            except Exception as exc:
                print(f"  Relevance evaluation failed for job {job['id']} / user {user_id}: {exc}")
                continue

            supabase.table("user_job_matches").insert({
                "user_id": user_id,
                "job_id": job["id"],
                "score": int(result.get("score", 0)),
                "reasoning": result.get("reasoning"),
            }).execute()
