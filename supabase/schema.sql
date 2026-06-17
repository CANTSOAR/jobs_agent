-- ============================================================
-- Job Opportunity Agent — full schema.
--
-- This file is the single source of truth for the database. To
-- change the schema: run delete.sql, edit this file, then run this
-- file again. Don't hand-write one-off ALTERs once real data exists
-- — fold the change in here instead and do a clean rebuild.
-- ============================================================

create extension if not exists pgcrypto;

-- ---------- Whitelisting ----------
create table public.whitelisted_users (
  email text primary key,
  username text unique,
  created_at timestamptz not null default now()
);

-- ---------- Profiles (1:1 with auth.users) ----------
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text unique,
  first_name text,
  resume_text text,
  goal_description text,
  -- The user's LinkedIn `li_at` session cookie, only populated if they
  -- explicitly opt in to LinkedIn scraping from the dashboard.
  linkedin_session_cookie text,
  created_at timestamptz not null default now()
);

-- ---------- Companies ----------
create table public.companies (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  careers_page_url text not null unique,
  favicon_url text,
  linkedin_url text,
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  rejection_reason text,
  requested_by uuid references auth.users(id) on delete set null,
  last_scraped_content text,
  last_scraped_hash text,
  last_scraped_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.user_company_subscriptions (
  user_id uuid not null references auth.users(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, company_id)
);

create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  title text not null,
  url text,
  location text,
  first_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

-- ---------- Company LinkedIn posts ----------
create table public.company_linkedin_posts (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  post_url text not null,
  post_text text,
  is_actionable boolean not null default false,
  agent_reasoning text,
  first_seen_at timestamptz not null default now(),
  unique (company_id, post_url)
);

-- ---------- LinkedIn job searches ----------
create table public.linkedin_searches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  search_url text not null,
  last_scraped_at timestamptz,
  created_at timestamptz not null default now(),
  unique (user_id, search_url)
);

create table public.linkedin_search_results (
  id uuid primary key default gen_random_uuid(),
  search_id uuid not null references public.linkedin_searches(id) on delete cascade,
  job_title text not null,
  company_name text,
  job_url text not null,
  first_seen_at timestamptz not null default now(),
  unique (search_id, job_url)
);

-- ---------- Job relevance matches ----------
create table public.user_job_matches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null references public.jobs(id) on delete cascade,
  score integer not null check (score >= 0 and score <= 100),
  reasoning text,
  status text not null default 'new' check (status in ('new', 'notified', 'dismissed')),
  created_at timestamptz not null default now(),
  unique (user_id, job_id)
);

-- ---------- On-demand agent run requests ----------
-- A whitelisted user can insert a row here to ask the agent to run before its next
-- scheduled cron tick. A separate lightweight poller (agent/poll_requests.py), run on
-- a tighter cron interval, picks these up.
create table public.run_requests (
  id uuid primary key default gen_random_uuid(),
  requested_by uuid references auth.users(id) on delete set null,
  status text not null default 'pending' check (status in ('pending', 'running', 'completed', 'failed')),
  requested_at timestamptz not null default now(),
  completed_at timestamptz
);

-- ---------- RLS ----------
alter table public.whitelisted_users enable row level security;
alter table public.profiles enable row level security;
alter table public.companies enable row level security;
alter table public.user_company_subscriptions enable row level security;
alter table public.jobs enable row level security;
alter table public.company_linkedin_posts enable row level security;
alter table public.linkedin_searches enable row level security;
alter table public.linkedin_search_results enable row level security;
alter table public.user_job_matches enable row level security;
alter table public.run_requests enable row level security;

-- Users can only check their own whitelist status (not enumerate everyone else's).
create policy "users can check their own whitelist status" on public.whitelisted_users
  for select using (email = (auth.jwt() ->> 'email'));

create policy "users manage their own profile" on public.profiles
  for all using (id = auth.uid()) with check (id = auth.uid());

create policy "view approved or own companies" on public.companies
  for select using (status = 'approved' or requested_by = auth.uid());

-- Users may submit new requests, but only as 'pending' and attributed to themselves.
-- (The agent updates status/favicon/cache using the service_role key, which bypasses RLS.)
create policy "request a company" on public.companies
  for insert with check (requested_by = auth.uid() and status = 'pending');

create policy "manage own subscriptions" on public.user_company_subscriptions
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "view jobs for subscribed companies" on public.jobs
  for select using (
    exists (
      select 1 from public.user_company_subscriptions s
      where s.company_id = jobs.company_id and s.user_id = auth.uid()
    )
  );

-- Only actionable posts are surfaced, and only to subscribers of that company.
create policy "view actionable posts for subscribed companies" on public.company_linkedin_posts
  for select using (
    is_actionable and exists (
      select 1 from public.user_company_subscriptions s
      where s.company_id = company_linkedin_posts.company_id and s.user_id = auth.uid()
    )
  );

create policy "manage own linkedin searches" on public.linkedin_searches
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "view own linkedin search results" on public.linkedin_search_results
  for select using (
    exists (
      select 1 from public.linkedin_searches s
      where s.id = linkedin_search_results.search_id and s.user_id = auth.uid()
    )
  );

create policy "users manage their own job matches" on public.user_job_matches
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Only whitelisted users can request/view on-demand agent runs.
create policy "whitelisted users can request a run" on public.run_requests
  for insert with check (
    requested_by = auth.uid()
    and exists (select 1 from public.whitelisted_users w where w.email = auth.jwt() ->> 'email')
  );

create policy "whitelisted users can view run requests" on public.run_requests
  for select using (
    exists (select 1 from public.whitelisted_users w where w.email = auth.jwt() ->> 'email')
  );
