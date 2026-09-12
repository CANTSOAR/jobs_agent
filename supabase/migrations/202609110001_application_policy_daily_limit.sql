-- Mirror the worker's hard submission ceiling in the database so direct API or
-- SQL writes cannot bypass the dashboard's 0-20 input range.

begin;

alter table public.application_policies
  drop constraint if exists application_policies_max_daily_submissions_check;

alter table public.application_policies
  add constraint application_policies_max_daily_submissions_check
  check (max_daily_submissions between 0 and 20) not valid;

alter table public.application_policies
  validate constraint application_policies_max_daily_submissions_check;

commit;
