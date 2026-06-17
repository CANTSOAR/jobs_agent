import json
import os
from datetime import datetime, timezone

from openai import OpenAI

from scraper.html_utils import (
    extract_favicon_url,
    extract_linkedin_company_url,
    extract_visible_text,
    fetch_html,
    hash_content,
)

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
)

REVIEW_PROMPT = """You are reviewing a URL submitted as a company's job/careers page.
Company name: {name}
URL: {url}

Below is the visible text scraped from that URL. Decide whether it is genuinely a
careers/jobs page (it lists open roles or clearly links to them), as opposed to a
broken link, login wall, unrelated page, or a page with no job content.

Respond with ONLY valid JSON: {{"approve": true or false, "reason": "<one sentence>"}}

Page text (truncated):
---
{page_text}
---
"""


def review_pending_companies(supabase):
    pending = supabase.table("companies").select("*").eq("status", "pending").execute().data

    for company in pending:
        name = company["name"]
        url = company["careers_page_url"]
        print(f"Reviewing company request: {name} ({url})")

        try:
            html = fetch_html(url)
        except Exception as exc:
            supabase.table("companies").update({
                "status": "rejected",
                "rejection_reason": f"Could not fetch URL: {exc}",
            }).eq("id", company["id"]).execute()
            continue

        favicon_url = extract_favicon_url(html, url)
        linkedin_url = extract_linkedin_company_url(html)
        page_text = extract_visible_text(html)

        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{
                    "role": "user",
                    "content": REVIEW_PROMPT.format(name=name, url=url, page_text=page_text[:8000]),
                }],
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
        except Exception as exc:
            print(f"  Review failed for {name}: {exc}")
            continue

        if result.get("approve"):
            supabase.table("companies").update({
                "status": "approved",
                "favicon_url": favicon_url,
                "linkedin_url": linkedin_url,
                "last_scraped_content": page_text,
                "last_scraped_hash": hash_content(page_text),
                "last_scraped_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", company["id"]).execute()
            print(f"  Approved: {name}")
        else:
            supabase.table("companies").update({
                "status": "rejected",
                "favicon_url": favicon_url,
                "rejection_reason": result.get("reason", "Rejected by AI review."),
            }).eq("id", company["id"]).execute()
            print(f"  Rejected: {name} — {result.get('reason')}")
