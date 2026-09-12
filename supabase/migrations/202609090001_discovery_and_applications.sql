-- Add structured feed ingestion, mailbox signals, and guarded application tracking.
-- This migration is additive: it preserves all existing profiles, jobs, and matches.

begin;

create extension if not exists pgcrypto;

alter table public.profiles
  add column if not exists application_profile jsonb not null default '{}'::jsonb,
  add column if not exists job_preferences jsonb not null default '{}'::jsonb,
  add column if not exists feed_discovery_enabled boolean not null default true,
  add column if not exists last_job_digest_at timestamptz;

alter table public.companies
  alter column careers_page_url drop not null,
  add column if not exists normalized_name text generated always as (
    lower(regexp_replace(btrim(name), '\s+', ' ', 'g'))
  ) stored,
  add column if not exists scrape_enabled boolean not null default true;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.companies'::regclass
      and conname = 'companies_normalized_name_key'
  ) then
    alter table public.companies
      add constraint companies_normalized_name_key unique (normalized_name);
  end if;
end
$$;

alter table public.jobs
  add column if not exists canonical_url text,
  add column if not exists dedupe_key text,
  add column if not exists description text,
  add column if not exists category text,
  add column if not exists terms text[] not null default '{}',
  add column if not exists sponsorship text,
  add column if not exists degrees text[] not null default '{}',
  add column if not exists posted_at timestamptz,
  add column if not exists source_updated_at timestamptz,
  add column if not exists discovery_method text not null default 'scrape',
  add column if not exists updated_at timestamptz not null default now();

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.jobs'::regclass
      and conname = 'jobs_dedupe_key_key'
  ) then
    alter table public.jobs add constraint jobs_dedupe_key_key unique (dedupe_key);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.jobs'::regclass
      and conname = 'jobs_discovery_method_check'
  ) then
    alter table public.jobs add constraint jobs_discovery_method_check
      check (discovery_method in ('scrape', 'feed', 'mixed'));
  end if;
end
$$;

create index if not exists jobs_active_posted_idx
  on public.jobs (is_active, posted_at desc);

create table if not exists public.ingestion_sources (
  id uuid primary key default gen_random_uuid(),
  key text not null unique,
  kind text not null check (kind in ('simplify_json', 'swelist_email', 'other')),
  url text not null,
  config jsonb not null default '{}'::jsonb,
  etag text,
  last_modified text,
  last_checked_at timestamptz,
  last_success_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.ingestion_runs (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references public.ingestion_sources(id) on delete cascade,
  status text not null default 'running'
    check (status in ('running', 'completed', 'not_modified', 'failed')),
  upstream_version text,
  records_seen integer not null default 0 check (records_seen >= 0),
  jobs_inserted integer not null default 0 check (jobs_inserted >= 0),
  jobs_updated integer not null default 0 check (jobs_updated >= 0),
  error text,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists public.job_source_records (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references public.ingestion_sources(id) on delete cascade,
  external_id text not null,
  job_id uuid not null references public.jobs(id) on delete cascade,
  source_url text,
  raw_payload jsonb not null default '{}'::jsonb,
  source_active boolean not null default true,
  source_updated_at timestamptz,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  last_seen_run_id uuid references public.ingestion_runs(id) on delete set null,
  updated_at timestamptz not null default now(),
  unique (source_id, external_id)
);

create index if not exists job_source_records_job_idx
  on public.job_source_records (job_id);

create table if not exists public.inbound_messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  provider text not null,
  provider_message_id text not null,
  sender text,
  recipients text[] not null default '{}',
  subject text,
  received_at timestamptz,
  message_type text not null default 'unknown' check (message_type in (
    'swelist_digest', 'application_confirmation', 'assessment', 'interview',
    'rejection', 'offer', 'other', 'unknown'
  )),
  parser_version text,
  status text not null default 'received'
    check (status in ('received', 'parsed', 'processed', 'ignored', 'failed')),
  error text,
  metadata jsonb not null default '{}'::jsonb,
  raw_body text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (provider, provider_message_id)
);

create table if not exists public.application_policies (
  user_id uuid primary key references auth.users(id) on delete cascade,
  default_mode text not null default 'track_only'
    check (default_mode in ('track_only', 'inspect', 'autofill', 'auto_submit_if_safe')),
  min_match_score integer not null default 80 check (min_match_score between 0 and 100),
  ats_allowlist text[] not null default '{}',
  company_allowlist text[] not null default '{}',
  auto_submit_authorized boolean not null default false,
  auto_submit_authorized_at timestamptz,
  require_review_on_unknown_question boolean not null default true,
  max_daily_submissions integer not null default 3 check (max_daily_submissions >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (not auto_submit_authorized or auto_submit_authorized_at is not null)
);

create table if not exists public.application_answers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  key text not null,
  question_pattern text not null,
  answer_value jsonb not null,
  answer_type text not null default 'text'
    check (answer_type in (
      'text', 'boolean', 'single_select', 'multi_select', 'number', 'date', 'file', 'other'
    )),
  approved_for_autofill boolean not null default false,
  approved_for_submission boolean not null default false,
  is_sensitive boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, key)
);

create table if not exists public.applications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null references public.jobs(id) on delete cascade,
  match_id uuid references public.user_job_matches(id) on delete set null,
  status text not null default 'queued' check (status in (
    'queued', 'claimed', 'inspected', 'needs_review', 'ready_to_submit',
    'submitting', 'submitted', 'submission_unknown', 'assessment', 'interview',
    'rejected', 'offer', 'withdrawn', 'skipped', 'failed'
  )),
  mode text not null default 'track_only'
    check (mode in ('track_only', 'inspect', 'autofill', 'auto_submit_if_safe')),
  priority integer not null default 0,
  adapter text,
  target_url text,
  application_url text,
  claimed_by text,
  claimed_at timestamptz,
  claim_expires_at timestamptz,
  inspection_data jsonb not null default '{}'::jsonb,
  form_snapshot jsonb not null default '{}'::jsonb,
  form_fingerprint text,
  unknown_fields jsonb not null default '[]'::jsonb
    check (jsonb_typeof(unknown_fields) = 'array'),
  resume_snapshot jsonb not null default '{}'::jsonb,
  answers_snapshot jsonb not null default '{}'::jsonb,
  submission_authorized_at timestamptz,
  confirmation_id text,
  confirmation_url text,
  evidence_path text,
  queued_at timestamptz not null default now(),
  submitted_at timestamptz,
  last_error text,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, job_id)
);

create index if not exists applications_queue_idx
  on public.applications (priority desc, created_at)
  where status in ('queued', 'claimed');

create table if not exists public.application_events (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  event_type text not null,
  from_status text,
  to_status text,
  actor text not null default 'system',
  message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists application_events_application_idx
  on public.application_events (application_id, created_at desc);

create table if not exists public.submission_authorizations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  application_id uuid not null references public.applications(id) on delete cascade,
  form_fingerprint text not null,
  authorized_at timestamptz not null default now(),
  expires_at timestamptz,
  revoked_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (application_id, form_fingerprint)
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists jobs_set_updated_at on public.jobs;
create trigger jobs_set_updated_at before update on public.jobs
  for each row execute function public.set_updated_at();
drop trigger if exists ingestion_sources_set_updated_at on public.ingestion_sources;
create trigger ingestion_sources_set_updated_at before update on public.ingestion_sources
  for each row execute function public.set_updated_at();
drop trigger if exists job_source_records_set_updated_at on public.job_source_records;
create trigger job_source_records_set_updated_at before update on public.job_source_records
  for each row execute function public.set_updated_at();
drop trigger if exists inbound_messages_set_updated_at on public.inbound_messages;
create trigger inbound_messages_set_updated_at before update on public.inbound_messages
  for each row execute function public.set_updated_at();
drop trigger if exists application_policies_set_updated_at on public.application_policies;
create trigger application_policies_set_updated_at before update on public.application_policies
  for each row execute function public.set_updated_at();
drop trigger if exists application_answers_set_updated_at on public.application_answers;
create trigger application_answers_set_updated_at before update on public.application_answers
  for each row execute function public.set_updated_at();
drop trigger if exists applications_set_updated_at on public.applications;
create trigger applications_set_updated_at before update on public.applications
  for each row execute function public.set_updated_at();

create or replace function public.log_application_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if tg_op = 'INSERT' then
    insert into public.application_events (
      application_id, event_type, to_status, actor, metadata
    ) values (
      new.id, 'created', new.status, coalesce(new.claimed_by, 'system'),
      jsonb_build_object('mode', new.mode)
    );
  elsif old.status is distinct from new.status then
    insert into public.application_events (
      application_id, event_type, from_status, to_status, actor, metadata
    ) values (
      new.id, 'status_changed', old.status, new.status,
      coalesce(new.claimed_by, old.claimed_by, 'system'), '{}'::jsonb
    );
  elsif old.claimed_by is distinct from new.claimed_by then
    insert into public.application_events (
      application_id, event_type, from_status, to_status, actor, metadata
    ) values (
      new.id, 'claim_changed', old.status, new.status,
      coalesce(new.claimed_by, old.claimed_by, 'system'),
      jsonb_build_object('claim_expires_at', new.claim_expires_at)
    );
  end if;
  return new;
end;
$$;

drop trigger if exists applications_log_change on public.applications;
create trigger applications_log_change
  after insert or update on public.applications
  for each row execute function public.log_application_change();

create or replace function public.queue_application(
  p_job_id uuid,
  p_mode text default 'autofill'
)
returns setof public.applications
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user_id uuid := auth.uid();
  v_job public.jobs%rowtype;
  v_application public.applications%rowtype;
begin
  if v_user_id is null then
    raise exception 'authentication required';
  end if;
  if p_mode not in ('track_only', 'inspect', 'autofill') then
    raise exception 'unsupported queue mode';
  end if;
  if not exists (
    select 1 from public.whitelisted_users w
    where w.email = auth.jwt() ->> 'email'
  ) then
    raise exception 'user is not whitelisted';
  end if;

  select * into v_job from public.jobs where id = p_job_id and is_active;
  if not found or coalesce(v_job.url, '') = '' then
    raise exception 'active job with application URL not found';
  end if;

  insert into public.applications (
    user_id, job_id, status, mode, target_url, application_url
  ) values (
    v_user_id, v_job.id, 'queued', p_mode, v_job.url, v_job.url
  )
  on conflict (user_id, job_id) do nothing
  returning * into v_application;

  if v_application.id is null then
    select * into v_application
    from public.applications
    where user_id = v_user_id and job_id = p_job_id;
  end if;
  return next v_application;
end;
$$;

revoke all on function public.queue_application(uuid, text) from public, anon;
grant execute on function public.queue_application(uuid, text) to authenticated;

create or replace function public.authorize_application_submission(
  p_application_id uuid,
  p_form_fingerprint text
)
returns setof public.applications
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user_id uuid := auth.uid();
  v_application public.applications%rowtype;
  v_authorized_at timestamptz := now();
begin
  if v_user_id is null then
    raise exception 'authentication required';
  end if;
  if coalesce(btrim(p_form_fingerprint), '') = '' then
    raise exception 'form fingerprint is required';
  end if;

  update public.applications
  set status = 'queued',
      mode = 'auto_submit_if_safe',
      submission_authorized_at = v_authorized_at,
      queued_at = v_authorized_at,
      claim_expires_at = null,
      last_error = null
  where id = p_application_id
    and user_id = v_user_id
    and status = 'ready_to_submit'
    and form_fingerprint = p_form_fingerprint
  returning * into v_application;

  if v_application.id is null then
    raise exception 'application is not ready or its form changed';
  end if;

  insert into public.submission_authorizations (
    user_id, application_id, form_fingerprint, authorized_at, expires_at
  ) values (
    v_user_id, v_application.id, p_form_fingerprint,
    v_authorized_at, v_authorized_at + interval '30 minutes'
  )
  on conflict (application_id, form_fingerprint) do update
  set authorized_at = excluded.authorized_at,
      expires_at = excluded.expires_at,
      revoked_at = null;

  return next v_application;
end;
$$;

revoke all on function public.authorize_application_submission(uuid, text) from public, anon;
grant execute on function public.authorize_application_submission(uuid, text) to authenticated;

create or replace function public.claim_next_application(
  p_worker_id text,
  p_lease_minutes integer default 30
)
returns setof public.applications
language sql
security definer
set search_path = public
as $$
  with candidate as (
    select a.id
    from public.applications a
    where a.mode <> 'track_only'
      and (
        a.status = 'queued'
        or (
          a.status = 'claimed'
          and a.claim_expires_at is not null
          and a.claim_expires_at < now()
        )
      )
    order by a.priority desc, a.created_at
    for update skip locked
    limit 1
  )
  update public.applications a
  set status = 'claimed',
      claimed_by = p_worker_id,
      claimed_at = now(),
      claim_expires_at = now() + make_interval(mins => greatest(1, least(p_lease_minutes, 1440))),
      attempt_count = a.attempt_count + 1,
      last_error = null
  from candidate
  where a.id = candidate.id
  returning a.*;
$$;

revoke all on function public.claim_next_application(text, integer) from public, anon, authenticated;
grant execute on function public.claim_next_application(text, integer) to service_role;

create or replace function public.ingest_job_batch(
  p_source_id uuid,
  p_run_id uuid,
  p_records jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_record jsonb;
  v_company_id uuid;
  v_job_id uuid;
  v_existing_method text;
  v_external_id text;
  v_company_name text;
  v_title text;
  v_dedupe_key text;
  v_source_active boolean;
  v_inserted integer := 0;
  v_updated integer := 0;
begin
  if jsonb_typeof(p_records) <> 'array' then
    raise exception 'p_records must be a JSON array';
  end if;
  if not exists (
    select 1 from public.ingestion_runs r
    where r.id = p_run_id and r.source_id = p_source_id and r.status = 'running'
  ) then
    raise exception 'ingestion run % is not running for source %', p_run_id, p_source_id;
  end if;

  for v_record in select value from jsonb_array_elements(p_records)
  loop
    v_external_id := nullif(btrim(v_record->>'external_id'), '');
    v_company_name := nullif(btrim(v_record->>'company_name'), '');
    v_title := nullif(btrim(v_record->>'title'), '');
    v_dedupe_key := nullif(btrim(v_record->>'dedupe_key'), '');
    v_source_active := coalesce((v_record->>'source_active')::boolean, false);

    if v_external_id is null or v_company_name is null or v_title is null or v_dedupe_key is null then
      raise exception 'normalized record lacks external_id, company_name, title, or dedupe_key: %', v_record;
    end if;

    insert into public.companies (name, careers_page_url, scrape_enabled, status)
    values (v_company_name, null, false, 'approved')
    on conflict (normalized_name) do update set name = excluded.name
    returning id into v_company_id;

    select sr.job_id into v_job_id
    from public.job_source_records sr
    where sr.source_id = p_source_id and sr.external_id = v_external_id;

    if v_job_id is null then
      select j.id, j.discovery_method into v_job_id, v_existing_method
      from public.jobs j
      where j.dedupe_key = v_dedupe_key
        or (
          j.dedupe_key is null
          and j.url = nullif(v_record->>'url', '')
        )
      order by (j.dedupe_key = v_dedupe_key) desc nulls last
      limit 1;

      if v_job_id is null then
        insert into public.jobs (
          company_id, title, url, canonical_url, dedupe_key, location,
          category, terms, sponsorship, degrees, posted_at, source_updated_at,
          discovery_method, is_active
        ) values (
          v_company_id,
          v_title,
          nullif(v_record->>'url', ''),
          nullif(v_record->>'canonical_url', ''),
          v_dedupe_key,
          nullif(v_record->>'location', ''),
          nullif(v_record->>'category', ''),
          array(select jsonb_array_elements_text(coalesce(v_record->'terms', '[]'::jsonb))),
          nullif(v_record->>'sponsorship', ''),
          array(select jsonb_array_elements_text(coalesce(v_record->'degrees', '[]'::jsonb))),
          nullif(v_record->>'posted_at', '')::timestamptz,
          nullif(v_record->>'source_updated_at', '')::timestamptz,
          'feed',
          v_source_active
        ) returning id into v_job_id;
        v_inserted := v_inserted + 1;
      else
        update public.jobs
        set dedupe_key = coalesce(dedupe_key, v_dedupe_key),
            discovery_method = case when discovery_method = 'scrape' then 'mixed' else discovery_method end
        where id = v_job_id;
        v_updated := v_updated + 1;
      end if;

      insert into public.job_source_records (
        source_id, external_id, job_id, source_url, raw_payload, source_active,
        source_updated_at, last_seen_run_id
      ) values (
        p_source_id, v_external_id, v_job_id, nullif(v_record->>'url', ''),
        coalesce(v_record->'raw_payload', '{}'::jsonb), v_source_active,
        nullif(v_record->>'source_updated_at', '')::timestamptz, p_run_id
      );
    else
      v_updated := v_updated + 1;
      update public.job_source_records
      set source_url = nullif(v_record->>'url', ''),
          raw_payload = coalesce(v_record->'raw_payload', '{}'::jsonb),
          source_active = v_source_active,
          source_updated_at = nullif(v_record->>'source_updated_at', '')::timestamptz,
          last_seen_at = now(),
          last_seen_run_id = p_run_id
      where source_id = p_source_id and external_id = v_external_id;
    end if;

    update public.jobs
    set company_id = v_company_id,
        title = v_title,
        url = nullif(v_record->>'url', ''),
        canonical_url = nullif(v_record->>'canonical_url', ''),
        location = nullif(v_record->>'location', ''),
        category = nullif(v_record->>'category', ''),
        terms = array(select jsonb_array_elements_text(coalesce(v_record->'terms', '[]'::jsonb))),
        sponsorship = nullif(v_record->>'sponsorship', ''),
        degrees = array(select jsonb_array_elements_text(coalesce(v_record->'degrees', '[]'::jsonb))),
        posted_at = nullif(v_record->>'posted_at', '')::timestamptz,
        source_updated_at = nullif(v_record->>'source_updated_at', '')::timestamptz,
        is_active = case
          when v_source_active then true
          when discovery_method = 'feed' then false
          else is_active
        end,
        last_seen_at = now()
    where id = v_job_id;
  end loop;

  return jsonb_build_object(
    'processed', jsonb_array_length(p_records),
    'jobs_inserted', v_inserted,
    'jobs_updated', v_updated
  );
end;
$$;

revoke all on function public.ingest_job_batch(uuid, uuid, jsonb) from public, anon, authenticated;
grant execute on function public.ingest_job_batch(uuid, uuid, jsonb) to service_role;

create or replace function public.finalize_ingestion_run(p_source_id uuid, p_run_id uuid)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_deactivated integer := 0;
begin
  update public.job_source_records
  set source_active = false
  where source_id = p_source_id
    and last_seen_run_id is distinct from p_run_id
    and source_active;
  get diagnostics v_deactivated = row_count;

  update public.jobs j
  set is_active = false
  where j.discovery_method = 'feed'
    and exists (select 1 from public.job_source_records sr where sr.job_id = j.id)
    and not exists (
      select 1 from public.job_source_records sr
      where sr.job_id = j.id and sr.source_active
    );

  update public.jobs j
  set discovery_method = 'scrape'
  where j.discovery_method = 'mixed'
    and exists (select 1 from public.job_source_records sr where sr.job_id = j.id)
    and not exists (
      select 1 from public.job_source_records sr
      where sr.job_id = j.id and sr.source_active
    );

  return v_deactivated;
end;
$$;

revoke all on function public.finalize_ingestion_run(uuid, uuid) from public, anon, authenticated;
grant execute on function public.finalize_ingestion_run(uuid, uuid) to service_role;

alter table public.ingestion_sources enable row level security;
alter table public.ingestion_runs enable row level security;
alter table public.job_source_records enable row level security;
alter table public.inbound_messages enable row level security;
alter table public.application_policies enable row level security;
alter table public.application_answers enable row level security;
alter table public.applications enable row level security;
alter table public.application_events enable row level security;
alter table public.submission_authorizations enable row level security;

drop policy if exists "whitelisted users can view ingestion sources" on public.ingestion_sources;
create policy "whitelisted users can view ingestion sources" on public.ingestion_sources
  for select using (
    exists (select 1 from public.whitelisted_users w where w.email = auth.jwt() ->> 'email')
  );

drop policy if exists "whitelisted users can view ingestion runs" on public.ingestion_runs;
create policy "whitelisted users can view ingestion runs" on public.ingestion_runs
  for select using (
    exists (select 1 from public.whitelisted_users w where w.email = auth.jwt() ->> 'email')
  );

drop policy if exists "users manage their own application policy" on public.application_policies;
create policy "users manage their own application policy" on public.application_policies
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "users manage their own approved answers" on public.application_answers;
create policy "users manage their own approved answers" on public.application_answers
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "users manage their own applications" on public.applications;
create policy "users manage their own applications" on public.applications
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "users view their own application events" on public.application_events;
create policy "users view their own application events" on public.application_events
  for select using (
    exists (
      select 1 from public.applications a
      where a.id = application_events.application_id and a.user_id = auth.uid()
    )
  );

drop policy if exists "users manage their own submission authorizations" on public.submission_authorizations;
create policy "users manage their own submission authorizations" on public.submission_authorizations
  for all using (
    user_id = auth.uid()
    and exists (
      select 1 from public.applications a
      where a.id = submission_authorizations.application_id and a.user_id = auth.uid()
    )
  ) with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.applications a
      where a.id = submission_authorizations.application_id and a.user_id = auth.uid()
    )
  );

do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'applications'
  ) then
    alter publication supabase_realtime add table public.applications;
  end if;
end
$$;

commit;
