from datetime import datetime, timezone

from scraper.html_utils import extract_visible_text, fetch_html, hash_content
from scraper.job_extraction import extract_new_jobs_from_diff


def _deactivate_missing_jobs(supabase, company_id, current_text):
    active_jobs = (
        supabase.table("jobs")
        .select("id, title")
        .eq("company_id", company_id)
        .eq("is_active", True)
        .execute()
        .data
    )

    missing = [job for job in active_jobs if job["title"] not in current_text]
    for job in missing:
        supabase.table("jobs").update({"is_active": False}).eq("id", job["id"]).execute()

    return len(missing)


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
                new_jobs = extract_new_jobs_from_diff(company["name"], url, "\n".join(added_lines))
            except Exception as exc:
                print(f"  Job extraction failed for {company['name']}: {exc}")
                new_jobs = []

            for job in new_jobs:
                supabase.table("jobs").insert({
                    "company_id": company["id"],
                    "title": job["title"],
                    "url": job.get("url"),
                    "location": job.get("location"),
                }).execute()

            print(f"  Found {len(new_jobs)} new job posting(s).")

        removed_count = _deactivate_missing_jobs(supabase, company["id"], new_text)
        if removed_count:
            print(f"  Deactivated {removed_count} job posting(s) no longer on the page.")

        supabase.table("companies").update({
            "last_scraped_content": new_text,
            "last_scraped_hash": new_hash,
            "last_scraped_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", company["id"]).execute()
