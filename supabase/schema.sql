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
  email_notifications_enabled boolean not null default true,
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
  is_active boolean not null default true,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
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
-- A whitelisted user can insert a row here to ask the agent to run right away
-- instead of waiting for the next scheduled cron tick.
create table public.run_requests (
  id uuid primary key default gen_random_uuid(),
  requested_by uuid references auth.users(id) on delete set null,
  status text not null default 'pending' check (status in ('pending', 'running', 'completed', 'failed')),
  -- 'full' = the regular scrape+evaluate+notify pipeline. 'evaluate_only' = skip
  -- scraping and just (re-)score jobs already in the system against the user's
  -- profile, then notify -- the "Find My Matches Now" button.
  request_type text not null default 'full' check (request_type in ('full', 'evaluate_only')),
  requested_at timestamptz not null default now(),
  completed_at timestamptz
);

-- Fires the GitHub Actions on-demand workflow (.github/workflows/agent-poll.yml) the
-- instant a row lands here, via a repository_dispatch call, instead of waiting on
-- GitHub's own (unreliable under 15min) cron schedule.
--
-- Requires the pg_net extension and a Supabase Vault secret named 'github_pat'
-- holding a fine-grained PAT (scoped to just this repo, Contents: Read and write).
-- That secret is NOT created here -- it has to be created once, manually, via:
--   select vault.create_secret('<your PAT>', 'github_pat', 'Triggers repository_dispatch on run_requests insert');
-- (Re-run that after a delete.sql + schema.sql rebuild; Vault secrets aren't dropped
-- by delete.sql, but a fresh Supabase project obviously won't have one yet.)
create extension if not exists pg_net;

create or replace function public.notify_github_on_run_request()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  pat text;
begin
  select decrypted_secret into pat from vault.decrypted_secrets where name = 'github_pat' limit 1;

  if pat is not null then
    perform net.http_post(
      url := 'https://api.github.com/repos/CANTSOAR/jobs_agent/dispatches',
      headers := jsonb_build_object(
        'Authorization', 'Bearer ' || pat,
        'Accept', 'application/vnd.github+json',
        'Content-Type', 'application/json'
      ),
      body := jsonb_build_object('event_type', 'run_request_created')
    );
  end if;

  return new;
end;
$$;

drop trigger if exists on_run_request_created on public.run_requests;
create trigger on_run_request_created
  after insert on public.run_requests
  for each row
  when (new.status = 'pending')
  execute function public.notify_github_on_run_request();

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

-- Any whitelisted user can browse/search all currently tracked jobs, not just ones
-- from companies they're subscribed to (the dedicated "Jobs" tab is a broad browse view).
create policy "whitelisted users can view jobs" on public.jobs
  for select using (
    exists (select 1 from public.whitelisted_users w where w.email = auth.jwt() ->> 'email')
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
