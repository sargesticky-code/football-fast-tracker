create or replace function public.ft_promote_verified_alias_v2()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_promoted integer := 0;
begin
  with ins as (
    insert into public.team_aliases(
      source,alias,canonical_hkjc_name,confidence,
      first_seen_hkt,last_seen_hkt,match_count,status,alias_source,updated_at
    )
    select
      r.source,
      r.alias,
      r.hkjc_name_en,
      r.confidence,
      r.last_seen_at,
      r.last_seen_at,
      greatest(1,r.distinct_event_count),
      'ACTIVE',
      'V2_VERIFIED',
      now()
    from public.team_alias_resolved_v2 r
    left join public.team_aliases legacy
      on legacy.source=r.source and legacy.alias=r.alias
    where legacy.alias is null
    on conflict(source,alias) do nothing
    returning 1
  )
  select count(*) into v_promoted from ins;

  return jsonb_build_object('promoted_to_legacy_registry',v_promoted);
end
$$;

create or replace function public.ft_alias_maintenance_v2()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_refresh jsonb;
  v_promote jsonb;
begin
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  return jsonb_build_object('refresh',v_refresh,'promotion',v_promote);
end
$$;

do $$
begin
  if exists(select 1 from cron.job where jobname='team-alias-v2-hourly') then
    perform cron.unschedule((select jobid from cron.job where jobname='team-alias-v2-hourly'));
  end if;
  perform cron.schedule(
    'team-alias-v2-hourly',
    '10 * * * *',
    'select public.ft_alias_maintenance_v2();'
  );
end
$$;
