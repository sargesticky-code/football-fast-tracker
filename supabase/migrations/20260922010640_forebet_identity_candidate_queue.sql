
create or replace view public.forebet_identity_candidate_queue_v
with (security_invoker = true)
as
select
  fa.hkjc_event_id,
  fa.kickoff_hkt,
  fa.league_zh as canonical_tournament,
  fa.home_en as hkjc_home_en,
  fa.away_en as hkjc_away_en,
  fa.state as forebet_state,
  fa.reason as forebet_reason,
  fa.source_competition,
  fa.source_home_team,
  fa.source_away_team,
  fa.fixture_match_score,
  fa.identity_status,
  fa.identity_source,
  fa.checked_at,
  case
    when nullif(trim(fa.source_competition),'') is null then false
    else exists (
      select 1
      from public.competition_name_master c
      where c.source='FOREBET'
        and c.source_key=public.ft_team_name_key(fa.source_competition)
        and c.canonical_tournament=fa.league_zh
        and c.status='VERIFIED'
    )
  end as competition_master_hit,
  case
    when nullif(trim(fa.source_home_team),'') is null then false
    else exists (
      select 1
      from public.team_name_context_master t
      where t.source='FOREBET'
        and t.source_key=public.ft_team_name_key(fa.source_home_team)
        and t.canonical_tournament=fa.league_zh
        and (
          nullif(trim(fa.source_competition),'') is null
          or t.competition_key=public.ft_team_name_key(fa.source_competition)
        )
        and t.hkjc_name_en=fa.home_en
        and t.status='VERIFIED'
    )
  end as home_context_master_hit,
  case
    when nullif(trim(fa.source_away_team),'') is null then false
    else exists (
      select 1
      from public.team_name_context_master t
      where t.source='FOREBET'
        and t.source_key=public.ft_team_name_key(fa.source_away_team)
        and t.canonical_tournament=fa.league_zh
        and (
          nullif(trim(fa.source_competition),'') is null
          or t.competition_key=public.ft_team_name_key(fa.source_competition)
        )
        and t.hkjc_name_en=fa.away_en
        and t.status='VERIFIED'
    )
  end as away_context_master_hit,
  case
    when fa.identity_status='CANDIDATE'
      then 'CANDIDATE_IDENTITY'
    when fa.state='FIXTURE_ONLY'
      and nullif(trim(fa.source_home_team),'') is null
      then 'LEGACY_FIXTURE_NO_RAW_NAME'
    when fa.state='UNRESOLVED'
      and nullif(trim(fa.source_home_team),'') is null
      then 'SOURCE_FIXTURE_NOT_OBSERVED'
    when fa.identity_status='CONTEXT_VERIFIED'
      and (
        not exists (
          select 1 from public.team_name_context_master t
          where t.source='FOREBET'
            and t.source_key=public.ft_team_name_key(fa.source_home_team)
            and t.canonical_tournament=fa.league_zh
            and t.hkjc_name_en=fa.home_en
            and t.status='VERIFIED'
        )
        or not exists (
          select 1 from public.team_name_context_master t
          where t.source='FOREBET'
            and t.source_key=public.ft_team_name_key(fa.source_away_team)
            and t.canonical_tournament=fa.league_zh
            and t.hkjc_name_en=fa.away_en
            and t.status='VERIFIED'
        )
      )
      then 'CONTEXT_PERSISTENCE_GAP'
    else 'OTHER_IDENTITY_REVIEW'
  end as queue_reason
from public.forebet_availability fa
where
  fa.state <> 'MODEL'
  or coalesce(fa.identity_status,'') in ('CANDIDATE','CONTEXT_VERIFIED')
  or (
    fa.state='FIXTURE_ONLY'
    and nullif(trim(fa.source_home_team),'') is null
  );

create or replace function public.ft_record_forebet_identity_queue_health()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_total integer;
  v_candidate integer;
  v_no_raw integer;
  v_not_observed integer;
  v_context_gap integer;
  v_payload jsonb;
begin
  select
    count(*)::int,
    count(*) filter(where queue_reason='CANDIDATE_IDENTITY')::int,
    count(*) filter(where queue_reason='LEGACY_FIXTURE_NO_RAW_NAME')::int,
    count(*) filter(where queue_reason='SOURCE_FIXTURE_NOT_OBSERVED')::int,
    count(*) filter(where queue_reason='CONTEXT_PERSISTENCE_GAP')::int
  into v_total,v_candidate,v_no_raw,v_not_observed,v_context_gap
  from public.forebet_identity_candidate_queue_v;

  v_payload := jsonb_build_object(
    'total_queue',v_total,
    'candidate_identity',v_candidate,
    'legacy_fixture_no_raw_name',v_no_raw,
    'source_fixture_not_observed',v_not_observed,
    'context_persistence_gap',v_context_gap
  );

  insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
  values(
    'FOREBET_IDENTITY_QUEUE','phase1',
    v_total::text,
    case when v_context_gap>0 then 'FAIL'
         when v_candidate>0 or v_no_raw>0 then 'WARN'
         else 'PASS' end,
    'Persistent Phase 1 Forebet identity backlog; resolve source/league/team variants once into static masters.',
    now(),
    v_payload
  )
  on conflict(source,metric) do update
  set value_text=excluded.value_text,
      status=excluded.status,
      notes=excluded.notes,
      observed_at=excluded.observed_at,
      raw=excluded.raw;

  return v_payload;
end
$$;

revoke all on function public.ft_record_forebet_identity_queue_health() from public;
revoke all on function public.ft_record_forebet_identity_queue_health() from anon;
revoke all on function public.ft_record_forebet_identity_queue_health() from authenticated;
grant execute on function public.ft_record_forebet_identity_queue_health() to service_role;

select public.ft_record_forebet_identity_queue_health();
