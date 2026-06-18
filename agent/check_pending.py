import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

pending = supabase.table("run_requests").select("id").eq("status", "pending").execute().data
print(f"has_pending={'true' if pending else 'false'}")
