
create or replace function public.ft_refresh_womens_intl_team_names()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_rows integer := 0;
begin
  with awf_obs as (
    select hkjc_event_id,home_en team_en,kickoff_hkt
    from public.hkjc_upcoming_current
    where tournament='AWF' and nullif(trim(home_en),'') is not null
    union all
    select hkjc_event_id,away_en,kickoff_hkt
    from public.hkjc_upcoming_current
    where tournament='AWF' and nullif(trim(away_en),'') is not null
    union all
    select hkjc_event_id,home_en,kickoff_hkt
    from public.matches
    where tournament='AWF' and nullif(trim(home_en),'') is not null
    union all
    select hkjc_event_id,away_en,kickoff_hkt
    from public.matches
    where tournament='AWF' and nullif(trim(away_en),'') is not null
  ),
  grouped as (
    select
      'HKJC:'||public.ft_team_name_key(team_en) team_key,
      team_en,
      count(distinct hkjc_event_id) event_count,
      min(kickoff_hkt) first_seen_at,
      max(kickoff_hkt) last_seen_at
    from awf_obs
    where team_en like '% Women'
      and team_en not like '% U20%'
      and team_en not like '% U19%'
      and team_en not like '% U18%'
      and team_en not like '% U17%'
    group by team_en
  ),
  mapped as (
    select
      g.*,
      case trim(regexp_replace(g.team_en,' Women$','','i'))
        when 'Korea Republic' then 'South Korea'
        when 'Korea DPR' then 'North Korea'
        when 'Chinese Taipei' then 'Taiwan'
        else trim(regexp_replace(g.team_en,' Women$','','i'))
      end source_name
    from grouped g
  ),
  ins as (
    insert into public.team_name_master(
      source,source_name,source_key,team_key,hkjc_name_en,hkjc_name_zh,
      status,confidence,event_count,first_seen_at,last_seen_at,evidence_sources,updated_at
    )
    select
      'WOMENS_INTL_RESULTS',
      m.source_name,
      public.ft_team_name_key(m.source_name),
      m.team_key,
      te.hkjc_name_en,
      te.hkjc_name_zh,
      'VERIFIED',
      1.0,
      m.event_count,
      m.first_seen_at,
      m.last_seen_at,
      jsonb_build_array('HKJC_AWF_CANONICAL_COUNTRY'),
      now()
    from mapped m
    join public.team_entities_v2 te using(team_key)
    where public.ft_team_name_key(m.source_name) is not null
    on conflict(source,source_key,team_key) do update set
      source_name=excluded.source_name,
      hkjc_name_en=excluded.hkjc_name_en,
      hkjc_name_zh=excluded.hkjc_name_zh,
      status='VERIFIED',
      confidence=1.0,
      event_count=greatest(public.team_name_master.event_count,excluded.event_count),
      first_seen_at=least(public.team_name_master.first_seen_at,excluded.first_seen_at),
      last_seen_at=greatest(public.team_name_master.last_seen_at,excluded.last_seen_at),
      evidence_sources=excluded.evidence_sources,
      updated_at=now()
    returning 1
  )
  select count(*) into v_rows from ins;

  return jsonb_build_object('womens_intl_verified',v_rows);
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
  v_external jsonb;
  v_promote jsonb;
  v_master jsonb;
begin
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  v_external := public.ft_refresh_womens_intl_team_names();

  return jsonb_build_object(
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master,
    'external_team_names',v_external
  );
end
$$;
