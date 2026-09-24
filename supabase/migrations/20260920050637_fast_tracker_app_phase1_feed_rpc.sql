create or replace function public.ft_internal_app_phase1_feed(window_hours integer default 24)
returns jsonb
language sql
security definer
set search_path = pg_catalog, public, private, api, pg_temp
as $$
  with bounds as (
    select
      now() as starts_at,
      now() + make_interval(hours => greatest(1, least(coalesce(window_hours,24),48))) as ends_at
  )
  select coalesce(
    jsonb_agg(to_jsonb(v) order by v.kickoff_hkt, v.hkjc_event_id),
    '[]'::jsonb
  )
  from api.phase1_match_intelligence_v v
  cross join bounds b
  where v.selling is true
    and v.kickoff_hkt >= b.starts_at
    and v.kickoff_hkt < b.ends_at;
$$;

revoke all on function public.ft_internal_app_phase1_feed(integer) from public;
revoke all on function public.ft_internal_app_phase1_feed(integer) from anon;
revoke all on function public.ft_internal_app_phase1_feed(integer) from authenticated;
grant execute on function public.ft_internal_app_phase1_feed(integer) to service_role;
