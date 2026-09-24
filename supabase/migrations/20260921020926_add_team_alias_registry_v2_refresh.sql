create or replace function public.ft_refresh_team_alias_v2()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_entities integer := 0;
  v_evidence integer := 0;
  v_verified integer := 0;
  v_candidates integer := 0;
  v_ambiguous integer := 0;
  v_gaps integer := 0;
begin
  with raw_teams as (
    select home_en en,home_zh zh,kickoff_hkt seen_at,30 priority
    from public.hkjc_upcoming_current
    where nullif(trim(home_en),'') is not null
    union all
    select away_en,away_zh,kickoff_hkt,30
    from public.hkjc_upcoming_current
    where nullif(trim(away_en),'') is not null
    union all
    select home_en,home_zh,coalesce(updated_at,kickoff_hkt),10
    from public.matches
    where nullif(trim(home_en),'') is not null
    union all
    select away_en,away_zh,coalesce(updated_at,kickoff_hkt),10
    from public.matches
    where nullif(trim(away_en),'') is not null
  ),
  ranked as (
    select
      public.ft_team_name_key(en) name_key,
      trim(en) en,
      nullif(trim(zh),'') zh,
      seen_at,
      row_number() over(
        partition by public.ft_team_name_key(en)
        order by
          case when nullif(trim(zh),'') is not null
                 and public.ft_team_name_key(zh)<>public.ft_team_name_key(en)
               then 1 else 0 end desc,
          priority desc,
          seen_at desc nulls last
      ) rn,
      min(seen_at) over(partition by public.ft_team_name_key(en)) first_seen,
      max(seen_at) over(partition by public.ft_team_name_key(en)) last_seen
    from raw_teams
    where public.ft_team_name_key(en) is not null
  ),
  upserted as (
    insert into public.team_entities_v2(
      team_key,name_key,hkjc_name_en,hkjc_name_zh,first_seen_at,last_seen_at,status,updated_at
    )
    select
      'HKJC:'||name_key,
      name_key,
      en,
      case
        when zh is not null and public.ft_team_name_key(zh)<>name_key then zh
        else null
      end,
      first_seen,last_seen,'ACTIVE',now()
    from ranked
    where rn=1
    on conflict(team_key) do update set
      hkjc_name_en=excluded.hkjc_name_en,
      hkjc_name_zh=coalesce(excluded.hkjc_name_zh,public.team_entities_v2.hkjc_name_zh),
      first_seen_at=least(public.team_entities_v2.first_seen_at,excluded.first_seen_at),
      last_seen_at=greatest(public.team_entities_v2.last_seen_at,excluded.last_seen_at),
      status='ACTIVE',
      updated_at=now()
    returning 1
  )
  select count(*) into v_entities from upserted;

  with event_pairs as (
    select
      fp.hkjc_event_id,
      'H'::text team_side,
      trim(fp.forebet_home_team) alias,
      coalesce(hu.home_en,m.home_en) hkjc_en,
      coalesce(hu.tournament,m.tournament) tournament,
      coalesce(hu.kickoff_hkt,m.kickoff_hkt) kickoff_hkt,
      fp.fetched_at observed_at
    from public.forebet_predictions fp
    left join public.hkjc_upcoming_current hu on hu.hkjc_event_id=fp.hkjc_event_id
    left join public.matches m on m.hkjc_event_id=fp.hkjc_event_id
    where nullif(trim(fp.forebet_home_team),'') is not null
      and nullif(trim(coalesce(hu.home_en,m.home_en)),'') is not null
    union all
    select
      fp.hkjc_event_id,
      'A',
      trim(fp.forebet_away_team),
      coalesce(hu.away_en,m.away_en),
      coalesce(hu.tournament,m.tournament),
      coalesce(hu.kickoff_hkt,m.kickoff_hkt),
      fp.fetched_at
    from public.forebet_predictions fp
    left join public.hkjc_upcoming_current hu on hu.hkjc_event_id=fp.hkjc_event_id
    left join public.matches m on m.hkjc_event_id=fp.hkjc_event_id
    where nullif(trim(fp.forebet_away_team),'') is not null
      and nullif(trim(coalesce(hu.away_en,m.away_en)),'') is not null
  ),
  ins as (
    insert into public.team_alias_evidence_v2(
      source,alias,alias_key,team_key,hkjc_event_id,team_side,tournament,kickoff_hkt,
      evidence_type,confidence,observed_at,raw
    )
    select
      'FOREBET',
      ep.alias,
      public.ft_team_name_key(ep.alias),
      'HKJC:'||public.ft_team_name_key(ep.hkjc_en),
      ep.hkjc_event_id,
      ep.team_side,
      ep.tournament,
      ep.kickoff_hkt,
      'RECONCILED_EVENT',
      0.95,
      coalesce(ep.observed_at,now()),
      jsonb_build_object('hkjc_name_en',ep.hkjc_en)
    from event_pairs ep
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ep.hkjc_en)
    where public.ft_team_name_key(ep.alias) is not null
    on conflict do nothing
    returning 1
  )
  select count(*) into v_evidence from ins;

  with grouped as (
    select
      e.source,e.alias_key,e.team_key,
      (array_agg(e.alias order by e.observed_at desc))[1] alias,
      count(*) evidence_count,
      count(distinct e.hkjc_event_id) filter(where e.hkjc_event_id is not null) distinct_event_count,
      min(e.observed_at) first_seen_at,
      max(e.observed_at) last_seen_at
    from public.team_alias_evidence_v2 e
    group by e.source,e.alias_key,e.team_key
  ),
  targets as (
    select source,alias_key,count(*) target_count
    from grouped
    group by source,alias_key
  ),
  summary as (
    select g.*,t.target_count
    from grouped g
    join targets t using(source,alias_key)
  ),
  legacy_manual as (
    select source,public.ft_team_name_key(alias) alias_key
    from public.team_aliases
    where status='MANUAL' or alias_source in ('MANUAL_OVERRIDE','BOOTSTRAP_VERIFIED')
    group by 1,2
  ),
  classified as (
    select
      s.*,
      case
        when s.target_count>1 then 'AMBIGUOUS'
        when s.distinct_event_count>=2 then 'VERIFIED'
        when lm.alias_key is not null then 'VERIFIED'
        when s.alias_key=te.name_key then 'VERIFIED'
        else 'CANDIDATE'
      end status,
      case
        when s.target_count>1 then 0.0
        when s.distinct_event_count>=2 then 0.99
        when lm.alias_key is not null then 0.99
        when s.alias_key=te.name_key then 0.98
        else 0.75
      end confidence,
      case
        when s.target_count>1 then 'MULTI_TARGET_COLLISION'
        when s.distinct_event_count>=2 then 'REPEATED_RECONCILED_EVENTS'
        when lm.alias_key is not null then 'LEGACY_MANUAL_PLUS_EVENT'
        when s.alias_key=te.name_key then 'EXACT_HKJC_ENGLISH_PLUS_EVENT'
        else 'SINGLE_RECONCILED_EVENT'
      end verification_method
    from summary s
    join public.team_entities_v2 te on te.team_key=s.team_key
    left join legacy_manual lm
      on lm.source=s.source and lm.alias_key=s.alias_key
  )
  insert into public.team_alias_registry_v2(
    source,alias_key,team_key,alias,status,confidence,evidence_count,distinct_event_count,
    verification_method,first_seen_at,last_seen_at,updated_at
  )
  select
    source,alias_key,team_key,alias,status,confidence,evidence_count,distinct_event_count,
    verification_method,first_seen_at,last_seen_at,now()
  from classified
  on conflict(source,alias_key,team_key) do update set
    alias=excluded.alias,
    status=excluded.status,
    confidence=excluded.confidence,
    evidence_count=excluded.evidence_count,
    distinct_event_count=excluded.distinct_event_count,
    verification_method=excluded.verification_method,
    first_seen_at=excluded.first_seen_at,
    last_seen_at=excluded.last_seen_at,
    updated_at=now();

  with latest_avail as (
    select distinct on (fa.hkjc_event_id)
      fa.hkjc_event_id,fa.state,fa.reason,fa.checked_at
    from public.forebet_availability fa
    where fa.checked_at>=now()-interval '7 days'
    order by fa.hkjc_event_id,fa.checked_at desc
  ),
  gap_teams as (
    select
      la.hkjc_event_id,
      coalesce(hu.tournament,m.tournament) tournament,
      coalesce(hu.home_en,m.home_en) hkjc_en,
      coalesce(hu.home_zh,m.home_zh) hkjc_zh,
      la.reason,
      la.checked_at
    from latest_avail la
    left join public.hkjc_upcoming_current hu on hu.hkjc_event_id=la.hkjc_event_id
    left join public.matches m on m.hkjc_event_id=la.hkjc_event_id
    where la.state in ('UNRESOLVED','FIXTURE_ONLY')
      and nullif(trim(coalesce(hu.home_en,m.home_en)),'') is not null
    union all
    select
      la.hkjc_event_id,
      coalesce(hu.tournament,m.tournament),
      coalesce(hu.away_en,m.away_en),
      coalesce(hu.away_zh,m.away_zh),
      la.reason,
      la.checked_at
    from latest_avail la
    left join public.hkjc_upcoming_current hu on hu.hkjc_event_id=la.hkjc_event_id
    left join public.matches m on m.hkjc_event_id=la.hkjc_event_id
    where la.state in ('UNRESOLVED','FIXTURE_ONLY')
      and nullif(trim(coalesce(hu.away_en,m.away_en)),'') is not null
  ),
  grouped_gaps as (
    select
      'FOREBET'::text source,
      'HKJC:'||public.ft_team_name_key(hkjc_en) team_key,
      (array_agg(hkjc_en order by checked_at desc))[1] hkjc_name_en,
      (array_agg(hkjc_zh order by checked_at desc))[1] hkjc_name_zh,
      (array_agg(hkjc_event_id order by checked_at desc))[1] last_event_id,
      (array_agg(tournament order by checked_at desc))[1] tournament,
      (array_agg(reason order by checked_at desc))[1] reason,
      count(*) occurrence_count,
      min(checked_at) first_seen_at,
      max(checked_at) last_seen_at
    from gap_teams
    where public.ft_team_name_key(hkjc_en) is not null
    group by public.ft_team_name_key(hkjc_en)
  ),
  gap_upsert as (
    insert into public.team_alias_gap_queue_v2(
      source,team_key,hkjc_name_en,hkjc_name_zh,last_event_id,tournament,reason,
      occurrence_count,first_seen_at,last_seen_at,updated_at
    )
    select
      g.source,g.team_key,g.hkjc_name_en,g.hkjc_name_zh,g.last_event_id,g.tournament,g.reason,
      g.occurrence_count,g.first_seen_at,g.last_seen_at,now()
    from grouped_gaps g
    join public.team_entities_v2 te on te.team_key=g.team_key
    on conflict(source,team_key) do update set
      hkjc_name_en=excluded.hkjc_name_en,
      hkjc_name_zh=coalesce(excluded.hkjc_name_zh,public.team_alias_gap_queue_v2.hkjc_name_zh),
      last_event_id=excluded.last_event_id,
      tournament=excluded.tournament,
      reason=excluded.reason,
      occurrence_count=greatest(public.team_alias_gap_queue_v2.occurrence_count,excluded.occurrence_count),
      first_seen_at=least(public.team_alias_gap_queue_v2.first_seen_at,excluded.first_seen_at),
      last_seen_at=greatest(public.team_alias_gap_queue_v2.last_seen_at,excluded.last_seen_at),
      updated_at=now()
    returning 1
  )
  select count(*) into v_gaps from gap_upsert;

  select count(*) into v_verified from public.team_alias_registry_v2 where status='VERIFIED';
  select count(*) into v_candidates from public.team_alias_registry_v2 where status='CANDIDATE';
  select count(*) into v_ambiguous from public.team_alias_registry_v2 where status='AMBIGUOUS';

  insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
  values(
    'TEAM_ALIAS_V2','registry',
    v_verified::text,
    case when v_ambiguous>0 then 'WARN' else 'OK' end,
    'Shadow alias registry v2; production matcher not switched yet.',
    now(),
    jsonb_build_object(
      'entities_upserted',v_entities,
      'new_evidence_rows',v_evidence,
      'verified_aliases',v_verified,
      'candidate_aliases',v_candidates,
      'ambiguous_aliases',v_ambiguous,
      'gap_rows_upserted',v_gaps
    )
  )
  on conflict(source,metric) do update set
    value_text=excluded.value_text,
    status=excluded.status,
    notes=excluded.notes,
    observed_at=excluded.observed_at,
    raw=excluded.raw;

  return jsonb_build_object(
    'entities_upserted',v_entities,
    'new_evidence_rows',v_evidence,
    'verified_aliases',v_verified,
    'candidate_aliases',v_candidates,
    'ambiguous_aliases',v_ambiguous,
    'gap_rows_upserted',v_gaps
  );
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
    'select public.ft_refresh_team_alias_v2();'
  );
end
$$;
