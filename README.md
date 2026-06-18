# Job Opportunity AI Agent

An automated, AI-powered job search agent that actively monitors company recruiting pages and LinkedIn searches to find highly relevant job opportunities. It evaluates listings against your resume and career goals using DeepSeek AI, and sends email notifications only when it finds a strong match.

## Overview

The project is split into two primary components that work seamlessly together via a centralized **Supabase** PostgreSQL database:

1. **Next.js Web Dashboard** (`/web`)
   - A static, client-side web application (deployed via GitHub Pages) that allows whitelisted users to log in.
   - Users can upload their resume, set specific job goals, and manage which company pages or LinkedIn searches they want the agent to monitor.
2. **Python AI Agent Worker** (`/agent`)
   - An asynchronous backend worker designed to be run on a daily schedule (e.g., via a cron job).
   - Scrapes the requested job boards and LinkedIn.
   - Compares the HTML/content to the previous day's cached version to isolate *new* jobs.
   - Uses the **DeepSeek AI** to evaluate each new job against the user's uploaded resume and goals.
   - Emails (via SMTP) the matched user for highly-scored matches.

## Architecture & Data Flow

- **Database**: Supabase acts as the central source of truth. It handles user authentication, maintains the whitelist of allowed users, stores the job data, and logs the AI evaluation scores. Row Level Security (RLS) policies are in place to ensure users only see their own data.
- **Frontend**: A React application built with Next.js App Router and a vanilla CSS design system. It uses `output: 'export'` to remain completely static.
- **Backend Worker**: A Python script utilizing `playwright` for scraping, `openai` library connected to DeepSeek for LLM evaluations, and `supabase-py` for database interaction.

## Setup Instructions

### 1. Database (Supabase)
1. Create a new Supabase project.
2. Run [`supabase/schema.sql`](supabase/schema.sql) in the Supabase SQL editor to create all tables, columns, and RLS policies. `supabase/schema.sql` is the single source of truth for the schema — if you need to change it, edit that file and re-run [`supabase/delete.sql`](supabase/delete.sql) followed by `schema.sql` for a clean rebuild (only do this before you have real data; `delete.sql` is destructive).
3. Manually add your user email to the `whitelisted_users` table (or use the provided `whitelist_manager.ipynb` Jupyter notebook).

### 2. Environment Variables
Copy `.env.example` to `.env` and fill in your real keys:
- `SUPABASE_URL` and `SUPABASE_KEY` — `SUPABASE_KEY` must be the **service_role (secret)** key (Project Settings > API), since the agent needs to bypass RLS to write companies/jobs. Never use this key in the frontend.
- `DEEPSEEK_API_KEY` for AI evaluations.
- `SMTP_*` variables for email delivery.

`.env` is gitignored and should never be committed.

> Also copy `web/.env.example` to `web/.env.local` and fill in `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` (the public anon key — safe to expose to the browser) so the Next.js frontend can talk to Supabase.

### 3. Running the Web UI
Navigate to the `web` directory:
```bash
cd web
npm install
npm run dev
```

### 4. Running the Agent Worker
Navigate to the root directory, configure your Python environment, and execute the orchestrator:
```bash
pip install -r agent/requirements.txt
python agent/main.py
```

## Security & Whitelisting
Access to the Next.js dashboard is strictly gated. Even if a user creates an account via Supabase Auth, the UI will block them and prompt them to email the administrator unless their email explicitly exists in the `whitelisted_users` table.
