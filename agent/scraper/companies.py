import json
import os
from datetime import datetime, timezone

from openai import OpenAI

from scraper.html_utils import extract_visible_text, fetch_html, hash_content

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
)

EXTRACT_PROMPT = """You are comparing two snapshots of a company's careers page text to
find newly posted job openings.

Company: {name}
Careers page: {url}

Lines that are new in today's snapshot (not present in yesterday's):
---
{added_lines}
---

From these new lines, list any job postings that appear to be genuinely new openings
(ignore unrelated new lines, e.g. banners, cookie notices, unrelated news).

Respond with ONLY valid JSON: {{"jobs": [{{"title": "...", "url": "..." or null, "location": "..." or null}}]}}
If there are no new job postings, return {{"jobs": []}}.
"""


def scrape_companies(supabase):
    companies = supabase.table("companies").select("*").eq("status", "approved").execute().data

    for company in companies:
        url = company["careers_page_url"]
        print(f"Scraping {url}...")

        try:
            html = fetch_html(url)
        except Exception as exc:
            print(f"  Failed to fetch {url}: {exc}")
            continue

        new_text = extract_visible_text(html)
        new_hash = hash_content(new_text)

        if new_hash == company.get("last_scraped_hash"):
            print("  No changes detected.")
            continue

        old_lines = set((company.get("last_scraped_content") or "").splitlines())
        added_lines = [line for line in new_text.splitlines() if line not in old_lines]

        if added_lines:
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{
                        "role": "user",
                        "content": EXTRACT_PROMPT.format(
                            name=company["name"], url=url, added_lines="\n".join(added_lines)
                        ),
                    }],
                    response_format={"type": "json_object"},
                )
                new_jobs = json.loads(response.choices[0].message.content).get("jobs", [])
            except Exception as exc:
                print(f"  Job extraction failed for {company['name']}: {exc}")
                new_jobs = []

            for job in new_jobs:
                if not job.get("title"):
                    continue
                supabase.table("jobs").insert({
                    "company_id": company["id"],
                    "title": job["title"],
                    "url": job.get("url"),
                    "location": job.get("location"),
                }).execute()

            print(f"  Found {len(new_jobs)} new job posting(s).")

        supabase.table("companies").update({
            "last_scraped_content": new_text,
            "last_scraped_hash": new_hash,
            "last_scraped_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", company["id"]).execute()
