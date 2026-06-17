-- ============================================================
-- Drops every table this app owns.
--
-- Run this, then run schema.sql, whenever you want a clean rebuild.
-- DO NOT run this once there is real user data you care about —
-- it is unrecoverable.
-- ============================================================

drop table if exists public.run_requests cascade;
drop table if exists public.user_job_matches cascade;
drop table if exists public.linkedin_search_results cascade;
drop table if exists public.linkedin_searches cascade;
drop table if exists public.company_linkedin_posts cascade;
drop table if exists public.jobs cascade;
drop table if exists public.user_company_subscriptions cascade;
drop table if exists public.companies cascade;
drop table if exists public.profiles cascade;
drop table if exists public.whitelisted_users cascade;
