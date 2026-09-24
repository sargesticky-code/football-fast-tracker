
create or replace function public.ft_refresh_phase3_identity_registry()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_promoted integer := 0;
  v_candidates integer := 0;
  v_eligible integer := 0;
  v_mapped integer := 0;
begin
  with agg as (
    select
      hkjc_event_id,source,source_match_id,
      count(*)::int observations,
      min(match_confidence)::numeric min_conf,
      min(captured_at_hkt) first_seen,
      max(captured_at_hkt) last_seen
    from public.live_stats_history
    where source_match_id is not null
      and source_match_id <> ''
      and match_confidence >= 0.74
      and captured_at_hkt >= now()-interval '14 days'
    group by hkjc_event_id,source,source_match_id
  ),
  variants as (
    select hkjc_event_id,source,count(*)::int id_variants
    from agg
    group by hkjc_event_id,source
  ),
  stable as (
    select a.*,v.id_variants
    from agg a join variants v using(hkjc_event_id,source)
    where a.observations >= 3
      and a.min_conf >= 0.85
      and v.id_variants = 1
  ),
  ins as (
    insert into public.phase3_live_identity_map(
      hkjc_event_id,source,source_match_id,confidence,evidence_count,
      first_verified_at,last_verified_at,mapping_state,evidence,updated_at
    )
    select
      hkjc_event_id,source,source_match_id,min_conf,observations,
      first_seen,last_seen,'VERIFIED',
      jsonb_build_object(
        'method','recurring_repeated_live_observation',
        'minimum_confidence',min_conf,
        'observations',observations,
        'id_variants',id_variants
      ),
      now()
    from stable
    on conflict(hkjc_event_id,source) do update set
      confidence=greatest(public.phase3_live_identity_map.confidence,excluded.confidence),
      evidence_count=greatest(public.phase3_live_identity_map.evidence_count,excluded.evidence_count),
      first_verified_at=least(public.phase3_live_identity_map.first_verified_at,excluded.first_verified_at),
      last_verified_at=greatest(public.phase3_live_identity_map.last_verified_at,excluded.last_verified_at),
      evidence=excluded.evidence,
      updated_at=now()
    where public.phase3_live_identity_map.source_match_id=excluded.source_match_id
    returning 1
  )
  select count(*) into v_promoted from ins;

  with agg as (
    select
      hkjc_event_id,source,source_match_id,
      count(*)::int observations,
      min(match_confidence)::numeric min_conf,
      min(captured_at_hkt) first_seen,
      max(captured_at_hkt) last_seen
    from public.live_stats_history
    where source_match_id is not null
      and source_match_id <> ''
      and match_confidence >= 0.74
      and captured_at_hkt >= now()-interval '14 days'
    group by hkjc_event_id,source,source_match_id
  ),
  variants as (
    select hkjc_event_id,source,count(*)::int id_variants
    from agg group by hkjc_event_id,source
  ),
  src as (
    select a.*,v.id_variants,
      case
        when a.observations>=3 and a.min_conf>=0.85 and v.id_variants=1 then 'PROMOTABLE'
        else 'CANDIDATE'
      end candidate_state
    from agg a join variants v using(hkjc_event_id,source)
  ),
  ins as (
    insert into public.phase3_live_identity_candidate(
      hkjc_event_id,source,source_match_id,candidate_confidence,evidence_count,
      candidate_state,evidence,first_seen_at,last_seen_at
    )
    select
      hkjc_event_id,source,source_match_id,min_conf,observations,candidate_state,
      jsonb_build_object(
        'method','recurring_live_observation',
        'minimum_confidence',min_conf,
        'observations',observations,
        'id_variants',id_variants
      ),
      first_seen,last_seen
    from src
    on conflict(hkjc_event_id,source,source_match_id) do update set
      candidate_confidence=excluded.candidate_confidence,
      evidence_count=excluded.evidence_count,
      candidate_state=case
        when public.phase3_live_identity_candidate.candidate_state='REJECTED' then 'REJECTED'
        else excluded.candidate_state
      end,
      evidence=excluded.evidence,
      first_seen_at=least(public.phase3_live_identity_candidate.first_seen_at,excluded.first_seen_at),
      last_seen_at=greatest(public.phase3_live_identity_candidate.last_seen_at,excluded.last_seen_at)
    returning 1
  )
  select count(*) into v_candidates from ins;

  select eligible_rows,verified_rows
    into v_eligible,v_mapped
  from public.phase3_live_identity_coverage_health_v;

  insert into public.source_health(source,metric,status,value_text,notes,observed_at,raw)
  values(
    'PHASE3_IDENTITY_REGISTRY','heartbeat',
    case
      when v_eligible=0 then 'OK'
      when v_mapped=v_eligible then 'OK'
      when v_mapped=0 then 'WARN'
      else 'WARN'
    end,
    concat(v_mapped,'/',v_eligible),
    'Recurring Phase 3 live identity registry refresh.',
    now(),
    jsonb_build_object(
      'eligible',v_eligible,'mapped',v_mapped,
      'map_upserts',v_promoted,'candidate_upserts',v_candidates
    )
  )
  on conflict(source,metric) do update set
    status=excluded.status,value_text=excluded.value_text,notes=excluded.notes,
    observed_at=excluded.observed_at,raw=excluded.raw;

  return jsonb_build_object(
    'eligible',v_eligible,'mapped',v_mapped,
    'map_upserts',v_promoted,'candidate_upserts',v_candidates
  );
end;
$$;

revoke all on function public.ft_refresh_phase3_identity_registry() from public,anon,authenticated;
grant execute on function public.ft_refresh_phase3_identity_registry() to service_role;

do $$
declare j record;
begin
  for j in select jobid from cron.job where jobname='phase3-identity-registry-1min'
  loop perform cron.unschedule(j.jobid); end loop;
end $$;

select cron.schedule(
  'phase3-identity-registry-1min',
  '* * * * *',
  $cron$select public.ft_refresh_phase3_identity_registry();$cron$
);

select public.ft_refresh_phase3_identity_registry();
