import json
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from llm import get_client
from scraper.html_utils import fetch_html

ACTIONABLE_PROMPT = """A company posted the following update on LinkedIn. Decide whether
it represents an actionable opportunity for a job seeker (e.g. it announces hiring, a
new role, a team expansion, or an event aimed at candidates), as opposed to general
company news, marketing, or unrelated content.

Company: {name}
Post: {post_text}

Respond with ONLY valid JSON: {{"actionable": true or false, "reason": "<one sentence>"}}
"""


def _extract_posts(html: str) -> list[dict]:
    """
    Parses whatever LinkedIn exposes on a company's /posts/ page without a login
    session. LinkedIn shows little to no content here for guests, so this is
    best-effort and may often find nothing.
    """
    soup = BeautifulSoup(html, "html.parser")
    posts = []

    for card in soup.select("[data-urn], .feed-shared-update-v2"):
        link = card.select_one("a[href*='/posts/']") or card.select_one("a[href*='/feed/update/']")
        if not link or not link.get("href"):
            continue

        text = card.get_text(" ", strip=True)
        if not text:
            continue

        parts = urlsplit(link["href"])
        posts.append({
            "post_url": f"{parts.scheme}://{parts.netloc}{parts.path}",
            "post_text": text[:2000],
        })

    return posts


def scrape_company_posts(supabase):
    companies = supabase.table("companies").select("*").eq("status", "approved").execute().data

    for company in companies:
        linkedin_url = company.get("linkedin_url")
        if not linkedin_url:
            continue

        posts_url = linkedin_url.rstrip("/") + "/posts/"
        print(f"Checking LinkedIn posts for {company['name']} ({posts_url})")

        try:
            html = fetch_html(posts_url)
        except Exception as exc:
            print(f"  Failed to fetch posts page: {exc}")
            continue

        posts = _extract_posts(html)
        if not posts:
            print("  No public posts visible without login.")
            continue

        existing_urls = {
            row["post_url"]
            for row in supabase.table("company_linkedin_posts")
            .select("post_url")
            .eq("company_id", company["id"])
            .execute()
            .data
        }

        new_posts = [post for post in posts if post["post_url"] not in existing_urls]

        for post in new_posts:
            try:
                response = get_client().chat.completions.create(
                    model="deepseek-chat",
                    messages=[{
                        "role": "user",
                        "content": ACTIONABLE_PROMPT.format(name=company["name"], post_text=post["post_text"]),
                    }],
                    response_format={"type": "json_object"},
                )
                result = json.loads(response.choices[0].message.content)
            except Exception as exc:
                print(f"  Actionability check failed: {exc}")
                result = {"actionable": False, "reason": "evaluation failed"}

            supabase.table("company_linkedin_posts").insert({
                "company_id": company["id"],
                "post_url": post["post_url"],
                "post_text": post["post_text"],
                "is_actionable": bool(result.get("actionable")),
                "agent_reasoning": result.get("reason"),
            }).execute()

        print(f"  {len(new_posts)} new post(s) evaluated.")
