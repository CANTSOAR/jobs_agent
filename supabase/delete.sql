-- ============================================================
-- Drops every table this app owns.
--
-- Local/throwaway databases only. Existing environments must use the
-- additive files in migrations/. DO NOT run this against real user data.
-- ============================================================

drop table if exists public.run_requests cascade;
drop function if exists public.authorize_application_submission(uuid, text) cascade;
drop function if exists public.queue_application(uuid, text) cascade;
drop table if exists public.submission_authorizations cascade;
drop table if exists public.application_events cascade;
drop table if exists public.applications cascade;
drop table if exists public.application_answers cascade;
drop table if exists public.application_policies cascade;
drop table if exists public.user_job_matches cascade;
drop table if exists public.linkedin_search_results cascade;
drop table if exists public.linkedin_searches cascade;
drop table if exists public.company_linkedin_posts cascade;
drop table if exists public.inbound_messages cascade;
drop table if exists public.job_source_records cascade;
drop table if exists public.ingestion_runs cascade;
drop table if exists public.ingestion_sources cascade;
drop table if exists public.jobs cascade;
drop table if exists public.user_company_subscriptions cascade;
drop table if exists public.companies cascade;
drop table if exists public.profiles cascade;
drop table if exists public.whitelisted_users cascade;
