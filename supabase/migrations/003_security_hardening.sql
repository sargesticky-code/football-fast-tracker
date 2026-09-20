-- Harden Data API exposure for Fast Tracker.
-- Server-side ingestion uses service_role only. No public browser role gets table access yet.

alter view if exists public.fast_tracker_live_v set (security_invoker = true);
alter view if exists public.forebet_effective_v set (security_invoker = true);
alter view if exists public.fast_tracker_live_v2 set (security_invoker = true);

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

grant usage on schema public to service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;

alter default privileges for role postgres in schema public
  revoke select, insert, update, delete on tables from anon, authenticated;

alter default privileges for role postgres in schema public
  revoke usage, select on sequences from anon, authenticated;

alter default privileges for role postgres in schema public
  grant select, insert, update, delete on tables to service_role;

alter default privileges for role postgres in schema public
  grant usage, select on sequences to service_role;
