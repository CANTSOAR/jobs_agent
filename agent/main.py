import os
from supabase import create_client, Client
from dotenv import load_dotenv

from evaluator.company_review import review_pending_companies
from evaluator.relevance import evaluate_jobs
from notifications.notifier import send_alerts
from scraper.companies import scrape_companies
from scraper.company_posts import scrape_company_posts
from scraper.html_utils import close_browser
from scraper.linkedin import scrape_searches

# Load environment variables
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Initialize Supabase client
# NOTE: this must be the Supabase service_role (secret) key, not the anon/publishable
# key, otherwise the RLS policies on `companies`/`jobs` will block the agent's writes.
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def run_agent():
    print("Starting the Job Opportunity Agent daily run...")

    try:
        # 1. Review newly requested companies (DeepSeek decides approve/reject + grabs favicon)
        print("Reviewing pending company requests...")
        review_pending_companies(supabase)

        # 2. Scrape approved company pages, diffing against the cached content
        print("Scraping company pages...")
        scrape_companies(supabase)

        # 3. Check approved companies' LinkedIn pages for actionable posts
        print("Checking company LinkedIn posts...")
        scrape_company_posts(supabase)

        # 4. Scrape LinkedIn job searches (logged-out, simple diff against cache)
        print("Scraping LinkedIn searches...")
        scrape_searches(supabase)

        # 5. Evaluate new jobs against user profiles
        print("Evaluating new jobs...")
        evaluate_jobs(supabase)

        # 6. Send notifications
        print("Sending notifications...")
        send_alerts(supabase)
    finally:
        close_browser()

    print("Agent run complete.")


def evaluate_and_notify():
    """
    Scores every job not yet scored for every subscribed user, then emails the ones
    that clear the threshold. Skips scraping entirely -- for the "Find My Matches Now"
    button, where the point is to (re-)score jobs already in the system, not find new ones.
    """
    print("Evaluating jobs against profiles...")
    evaluate_jobs(supabase)

    print("Sending notifications...")
    send_alerts(supabase)

    print("Done.")


if __name__ == "__main__":
    run_agent()
