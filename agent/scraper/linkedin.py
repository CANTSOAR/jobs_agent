from datetime import datetime, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from scraper.html_utils import fetch_html

MAX_RESULTS_PER_SEARCH = 50


def _normalize_job_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _extract_job_cards(html: str) -> list[dict]:
    """
    Parses LinkedIn's logged-out job search results markup. No login/session is used,
    so LinkedIn may truncate, rate-limit, or change this markup at any time — this is
    best-effort, not a guaranteed feed.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.base-card") or soup.select("li.jobs-search-results__list-item")

    jobs = []
    for card in cards:
        link = card.select_one("a.base-card__full-link") or card.select_one("a[href*='/jobs/view/']")
        title_el = card.select_one("h3.base-search-card__title")
        company_el = card.select_one("h4.base-search-card__subtitle")

        if not link or not link.get("href") or not title_el:
            continue

        jobs.append({
            "job_title": title_el.get_text(strip=True),
            "company_name": company_el.get_text(strip=True) if company_el else None,
            "job_url": _normalize_job_url(link["href"]),
        })

    return jobs


def scrape_searches(supabase):
    searches = supabase.table("linkedin_searches").select("*").execute().data

    for search in searches:
        search_id = search["id"]
        url = search["search_url"]
        print(f"Scraping LinkedIn search: {url}")

        try:
            html = fetch_html(url)
        except Exception as exc:
            print(f"  Failed to fetch search: {exc}")
            continue

        jobs = _extract_job_cards(html)[:MAX_RESULTS_PER_SEARCH]

        existing_urls = {
            row["job_url"]
            for row in supabase.table("linkedin_search_results")
            .select("job_url")
            .eq("search_id", search_id)
            .execute()
            .data
        }

        new_jobs = [job for job in jobs if job["job_url"] not in existing_urls]

        for job in new_jobs:
            supabase.table("linkedin_search_results").insert({
                "search_id": search_id,
                **job,
            }).execute()

        supabase.table("linkedin_searches").update({
            "last_scraped_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", search_id).execute()

        print(f"  {len(new_jobs)} new job(s) out of {len(jobs)} scraped (logged-out, best-effort).")
