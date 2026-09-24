CREATE OR REPLACE FUNCTION private.ft_refresh_multisource_master_annotations()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'private', 'pg_temp'
AS $function$
declare
  v_updated integer := 0;
  v_rows integer := 0;
  v_observed_rows integer := 0;
  v_absent_rows integer := 0;
  v_pairs integer := 0;
  v_direct integer := 0;
  v_global integer := 0;
begin
  with base as (
    select
      m.hkjc_event_id,
      m.hkjc_home,
      m.hkjc_away,
      m.raw,
      case
        when jsonb_typeof(m.raw->'identity_evidence')='array'
          then m.raw->'identity_evidence'
        when nullif(m.raw->>'identity_evidence','') is not null
          then (m.raw->>'identity_evidence')::jsonb
        else '[]'::jsonb
      end evidence
    from private.multisource_consensus_current m
  ),
  ev as (
    select
      b.hkjc_event_id,b.hkjc_home,b.hkjc_away,
      upper(trim(e.value->>'source')) source,
      nullif(trim(e.value->>'home'),'') home_alias,
      nullif(trim(e.value->>'away'),'') away_alias
    from base b
    cross join lateral jsonb_array_elements(b.evidence) e(value)
  ),
  resolved as (
    select e.*,
      (
        exists(
          select 1 from public.team_name_master m
          where m.source=e.source
            and m.source_key=public.ft_team_name_key(e.home_alias)
            and m.team_key='HKJC:'||public.ft_team_name_key(e.hkjc_home)
            and m.status='VERIFIED'
        )
        and exists(
          select 1 from public.team_name_master m
          where m.source=e.source
            and m.source_key=public.ft_team_name_key(e.away_alias)
            and m.team_key='HKJC:'||public.ft_team_name_key(e.hkjc_away)
            and m.status='VERIFIED'
        )
      ) direct_hit,
      (
        exists(
          select 1 from public.team_name_global_lookup g
          where g.source_key=public.ft_team_name_key(e.home_alias)
            and g.team_key='HKJC:'||public.ft_team_name_key(e.hkjc_home)
        )
        and exists(
          select 1 from public.team_name_global_lookup g
          where g.source_key=public.ft_team_name_key(e.away_alias)
            and g.team_key='HKJC:'||public.ft_team_name_key(e.hkjc_away)
        )
      ) global_hit
    from ev e
  ),
  per_source as (
    select
      hkjc_event_id,source,
      bool_or(direct_hit) direct_hit,
      bool_or(global_hit) global_hit
    from resolved
    where nullif(source,'') is not null
    group by hkjc_event_id,source
  ),
  agg as (
    select
      hkjc_event_id,
      count(*)::int evidence_sources,
      count(*) filter(where direct_hit)::int direct_count,
      coalesce(string_agg(source,'+' order by source) filter(where direct_hit),'') direct_sources,
      count(*) filter(where global_hit)::int global_count,
      coalesce(string_agg(source,'+' order by source) filter(where global_hit),'') global_sources
    from per_source
    group by hkjc_event_id
  ),
  stats as (
    select
      b.hkjc_event_id,
      jsonb_array_length(b.evidence)::int evidence_items,
      coalesce(a.evidence_sources,0)::int evidence_sources,
      coalesce(a.direct_count,0)::int direct_count,
      coalesce(a.direct_sources,'') direct_sources,
      coalesce(a.global_count,0)::int global_count,
      coalesce(a.global_sources,'') global_sources
    from base b
    left join agg a using(hkjc_event_id)
  ),
  upd as (
    update private.multisource_consensus_current m
    set raw = coalesce(m.raw,'{}'::jsonb) || jsonb_build_object(
      'master_direct_source_count',s.direct_count,
      'master_direct_sources',s.direct_sources,
      'master_global_source_count',s.global_count,
      'master_global_sources',s.global_sources,
      'master_annotation_source','TEAM_NAME_MASTER_RUNTIME',
      'master_annotations_refreshed_at',now()
    )
    from stats s
    where m.hkjc_event_id=s.hkjc_event_id
      and (
        case when coalesce(m.raw->>'master_direct_source_count','') ~ '^\d+$'
          then (m.raw->>'master_direct_source_count')::int else 0 end
          is distinct from s.direct_count
        or coalesce(m.raw->>'master_direct_sources','') is distinct from s.direct_sources
        or case when coalesce(m.raw->>'master_global_source_count','') ~ '^\d+$'
          then (m.raw->>'master_global_source_count')::int else 0 end
          is distinct from s.global_count
        or coalesce(m.raw->>'master_global_sources','') is distinct from s.global_sources
      )
    returning 1
  )
  select count(*)::int into v_updated from upd;

  with base as (
    select
      m.hkjc_event_id,
      case
        when jsonb_typeof(m.raw->'identity_evidence')='array'
          then m.raw->'identity_evidence'
        when nullif(m.raw->>'identity_evidence','') is not null
          then (m.raw->>'identity_evidence')::jsonb
        else '[]'::jsonb
      end evidence,
      case when coalesce(m.raw->>'master_direct_source_count','') ~ '^\d+$'
        then (m.raw->>'master_direct_source_count')::int else 0 end direct_count,
      case when coalesce(m.raw->>'master_global_source_count','') ~ '^\d+$'
        then (m.raw->>'master_global_source_count')::int else 0 end global_count
    from private.multisource_consensus_current m
  )
  select
    count(*)::int,
    count(*) filter(where jsonb_array_length(evidence)>0)::int,
    count(*) filter(where jsonb_array_length(evidence)=0)::int,
    coalesce(sum(jsonb_array_length(evidence)),0)::int,
    coalesce(sum(direct_count),0)::int,
    coalesce(sum(global_count),0)::int
  into v_rows,v_observed_rows,v_absent_rows,v_pairs,v_direct,v_global
  from base;

  return jsonb_build_object(
    'updated_rows',v_updated,
    'rows',v_rows,
    'source_observed_rows',v_observed_rows,
    'source_absent_rows',v_absent_rows,
    'observed_source_pairs',v_pairs,
    'direct_master_pairs',v_direct,
    'global_master_pairs',v_global
  );
end
$function$;

CREATE OR REPLACE FUNCTION public.ft_record_one_for_all_alias_health()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'private', 'pg_temp'
AS $function$
declare
  v_total integer:=0;
  v_verified integer:=0;
  v_candidate integer:=0;
  v_ambiguous integer:=0;
  v_current integer:=0;
  v_observed_rows integer:=0;
  v_absent_rows integer:=0;
  v_observed_pairs integer:=0;
  v_direct_pairs integer:=0;
  v_global_only_pairs integer:=0;
  v_unresolved_pairs integer:=0;
  v_direct_rows integer:=0;
  v_global_rows integer:=0;
  v_sources jsonb:='{}'::jsonb;
  v_direct jsonb:='{}'::jsonb;
  v_global jsonb:='{}'::jsonb;
  v_unresolved jsonb:='[]'::jsonb;
  v_payload jsonb;
begin
  select
    count(*)::int,
    count(*) filter(where status='VERIFIED')::int,
    count(*) filter(where status='CANDIDATE')::int,
    count(*) filter(where status='AMBIGUOUS')::int
  into v_total,v_verified,v_candidate,v_ambiguous
  from public.team_name_master;

  select coalesce(jsonb_object_agg(source,stats order by source),'{}'::jsonb)
  into v_sources
  from (
    select source,
      jsonb_build_object(
        'verified',count(*) filter(where status='VERIFIED'),
        'candidate',count(*) filter(where status='CANDIDATE'),
        'ambiguous',count(*) filter(where status='AMBIGUOUS'),
        'total',count(*)
      ) stats
    from public.team_name_master
    group by source
  ) x;

  with active as (
    select m.*,
      case
        when jsonb_typeof(m.raw->'identity_evidence')='array' then m.raw->'identity_evidence'
        when nullif(m.raw->>'identity_evidence','') is not null then (m.raw->>'identity_evidence')::jsonb
        else '[]'::jsonb
      end evidence
    from private.multisource_consensus_current m
    join public.hkjc_upcoming_current u using(hkjc_event_id)
    where u.kickoff_hkt>=now()-interval '3 hours'
      and u.kickoff_hkt<now()+interval '48 hours'
  ),
  ev as (
    select
      a.hkjc_event_id,a.hkjc_home,a.hkjc_away,
      upper(trim(e.value->>'source')) source,
      nullif(trim(e.value->>'home'),'') home_alias,
      nullif(trim(e.value->>'away'),'') away_alias
    from active a
    cross join lateral jsonb_array_elements(a.evidence) e(value)
  ),
  resolved as (
    select e.*,
      (
        exists(select 1 from public.team_name_master m
          where m.source=e.source
            and m.source_key=public.ft_team_name_key(e.home_alias)
            and m.team_key='HKJC:'||public.ft_team_name_key(e.hkjc_home)
            and m.status='VERIFIED')
        and exists(select 1 from public.team_name_master m
          where m.source=e.source
            and m.source_key=public.ft_team_name_key(e.away_alias)
            and m.team_key='HKJC:'||public.ft_team_name_key(e.hkjc_away)
            and m.status='VERIFIED')
      ) direct_hit,
      (
        exists(select 1 from public.team_name_global_lookup g
          where g.source_key=public.ft_team_name_key(e.home_alias)
            and g.team_key='HKJC:'||public.ft_team_name_key(e.hkjc_home))
        and exists(select 1 from public.team_name_global_lookup g
          where g.source_key=public.ft_team_name_key(e.away_alias)
            and g.team_key='HKJC:'||public.ft_team_name_key(e.hkjc_away))
      ) global_hit
    from ev e
  ),
  per_source as (
    select hkjc_event_id,source,
           bool_or(direct_hit) direct_hit,
           bool_or(global_hit) global_hit,
           (array_agg(home_alias))[1] home_alias,
           (array_agg(away_alias))[1] away_alias
    from resolved
    where nullif(source,'') is not null
    group by hkjc_event_id,source
  ),
  row_stats as (
    select
      a.hkjc_event_id,
      jsonb_array_length(a.evidence) evidence_count,
      count(ps.source) filter(where ps.direct_hit) direct_count,
      count(ps.source) filter(where ps.global_hit) global_count
    from active a
    left join per_source ps using(hkjc_event_id)
    group by a.hkjc_event_id,a.evidence
  )
  select
    (select count(*)::int from active),
    (select count(*)::int from active where jsonb_array_length(evidence)>0),
    (select count(*)::int from active where jsonb_array_length(evidence)=0),
    (select count(*)::int from per_source),
    (select count(*)::int from per_source where direct_hit),
    (select count(*)::int from per_source where not direct_hit and global_hit),
    (select count(*)::int from per_source where not direct_hit and not global_hit),
    (select count(*)::int from row_stats where direct_count>0),
    (select count(*)::int from row_stats where direct_count=0 and global_count>0),
    coalesce((
      select jsonb_agg(jsonb_build_object(
        'hkjc_event_id',hkjc_event_id,'source',source,
        'home_alias',home_alias,'away_alias',away_alias
      ) order by hkjc_event_id,source)
      from per_source where not direct_hit and not global_hit
    ),'[]'::jsonb),
    coalesce((
      select jsonb_object_agg(source,cnt order by source)
      from (select source,count(*)::int cnt from per_source where direct_hit group by source) z
    ),'{}'::jsonb),
    coalesce((
      select jsonb_object_agg(source,cnt order by source)
      from (select source,count(*)::int cnt from per_source where global_hit group by source) z
    ),'{}'::jsonb)
  into
    v_current,v_observed_rows,v_absent_rows,v_observed_pairs,
    v_direct_pairs,v_global_only_pairs,v_unresolved_pairs,
    v_direct_rows,v_global_rows,v_unresolved,v_direct,v_global
  from active
  limit 1;

  v_payload := jsonb_build_object(
    'total_rows',v_total,
    'verified_rows',v_verified,
    'candidate_rows',v_candidate,
    'ambiguous_rows',v_ambiguous,
    'sources',v_sources,
    'current_hkjc_anchor_rows',v_current,
    'source_observed_rows',v_observed_rows,
    'source_absent_rows',v_absent_rows,
    'observed_source_pairs',v_observed_pairs,
    'direct_master_pairs',v_direct_pairs,
    'global_fallback_only_pairs',v_global_only_pairs,
    'unresolved_pairs',v_unresolved_pairs,
    'direct_master_rows',v_direct_rows,
    'global_fallback_rows',v_global_rows,
    'direct_master_row_rate',
      case when v_observed_rows>0 then round(v_direct_rows::numeric/v_observed_rows,4) else null end,
    'direct_hits_by_source',v_direct,
    'global_fallback_hits_by_source',v_global,
    'unresolved_current',v_unresolved
  );

  insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
  values(
    'TEAM_ALIAS_ONE_FOR_ALL','phase1',
    coalesce(v_direct_pairs,0)::text||'/'||coalesce(v_observed_pairs,0)::text,
    case when v_unresolved_pairs>0 then 'WARN' else 'OK' end,
    case
      when v_unresolved_pairs>0 then
        format('Current source identity still has %s unresolved source pair(s).',v_unresolved_pairs)
      when v_absent_rows>0 then
        format('All %s observed source pairs resolve through the master; %s current HKJC matches have no external source evidence and are classified as no-data.',v_observed_pairs,v_absent_rows)
      else
        format('All %s observed source pairs resolve through the one-for-all master.',v_observed_pairs)
    end,
    now(),v_payload
  )
  on conflict(source,metric) do update set
    value_text=excluded.value_text,status=excluded.status,notes=excluded.notes,
    observed_at=excluded.observed_at,raw=excluded.raw;

  return v_payload || jsonb_build_object(
    'status',case when v_unresolved_pairs>0 then 'WARN' else 'OK' end
  );
end
$function$;

CREATE OR REPLACE FUNCTION public.ft_record_forebet_identity_queue_health()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
declare
  v_total integer:=0;
  v_candidate integer:=0;
  v_no_raw integer:=0;
  v_not_observed integer:=0;
  v_context_gap integer:=0;
  v_current integer:=0;
  v_current_candidate integer:=0;
  v_current_no_raw integer:=0;
  v_current_not_observed integer:=0;
  v_current_context_gap integer:=0;
  v_payload jsonb;
  v_status text;
begin
  select
    count(*)::int,
    count(*) filter(where queue_reason='CANDIDATE_IDENTITY')::int,
    count(*) filter(where queue_reason='LEGACY_FIXTURE_NO_RAW_NAME')::int,
    count(*) filter(where queue_reason='SOURCE_FIXTURE_NOT_OBSERVED')::int,
    count(*) filter(where queue_reason='CONTEXT_PERSISTENCE_GAP')::int
  into v_total,v_candidate,v_no_raw,v_not_observed,v_context_gap
  from public.forebet_identity_candidate_queue_v;

  select
    count(*)::int,
    count(*) filter(where queue_reason='CANDIDATE_IDENTITY')::int,
    count(*) filter(where queue_reason='LEGACY_FIXTURE_NO_RAW_NAME')::int,
    count(*) filter(where queue_reason='SOURCE_FIXTURE_NOT_OBSERVED')::int,
    count(*) filter(where queue_reason='CONTEXT_PERSISTENCE_GAP')::int
  into v_current,v_current_candidate,v_current_no_raw,v_current_not_observed,v_current_context_gap
  from public.forebet_identity_candidate_queue_v
  where kickoff_hkt>=now()-interval '3 hours'
    and kickoff_hkt<now()+interval '48 hours';

  v_status := case
    when v_current_context_gap>0 then 'FAIL'
    when v_current_candidate>0 or v_current_no_raw>0 then 'WARN'
    else 'OK'
  end;

  v_payload := jsonb_build_object(
    'total_queue',v_total,
    'candidate_identity',v_candidate,
    'legacy_fixture_no_raw_name',v_no_raw,
    'source_fixture_not_observed',v_not_observed,
    'context_persistence_gap',v_context_gap,
    'current_queue',v_current,
    'current_candidate_identity',v_current_candidate,
    'current_legacy_fixture_no_raw_name',v_current_no_raw,
    'current_source_fixture_not_observed',v_current_not_observed,
    'current_context_persistence_gap',v_current_context_gap
  );

  insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
  values(
    'FOREBET_IDENTITY_QUEUE','phase1',
    v_current::text,v_status,
    case
      when v_status='FAIL' then 'Current Phase 1 Forebet identity has a context persistence gap requiring repair.'
      when v_status='WARN' then 'Current Phase 1 Forebet identity has an actionable alias backlog.'
      when v_total>0 then 'No current actionable Forebet identity backlog; historical/deferred queue retained for audit.'
      else 'Forebet identity queue is empty.'
    end,
    now(),v_payload
  )
  on conflict(source,metric) do update set
    value_text=excluded.value_text,status=excluded.status,notes=excluded.notes,
    observed_at=excluded.observed_at,raw=excluded.raw;

  return v_payload || jsonb_build_object('status',v_status);
end
$function$;

CREATE OR REPLACE FUNCTION private.ft_record_alias_runtime_health()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'private', 'pg_temp'
AS $function$
declare
  v_one jsonb;
  v_unresolved integer:=0;
  v_observed integer:=0;
  v_absent integer:=0;
  v_status text;
  v_payload jsonb;
begin
  select raw into v_one
  from public.source_health
  where source='TEAM_ALIAS_ONE_FOR_ALL' and metric='phase1';

  v_unresolved := coalesce((v_one->>'unresolved_pairs')::int,0);
  v_observed := coalesce((v_one->>'observed_source_pairs')::int,0);
  v_absent := coalesce((v_one->>'source_absent_rows')::int,0);
  v_status := case when v_unresolved>0 then 'WARN' else 'OK' end;

  v_payload := jsonb_build_object(
    'current_observed_source_pairs',v_observed,
    'current_unresolved_pairs',v_unresolved,
    'current_source_absent_rows',v_absent,
    'historical_backlog_retained',true
  );

  update public.source_health
  set status=v_status,
      notes=case
        when v_unresolved>0 then
          format('Alias registry has %s unresolved current source pair(s); historical candidates remain quarantined.',v_unresolved)
        else
          format('Current alias path resolves all %s observed source pairs; historical candidate/ambiguous rows remain quarantined for audit.',v_observed)
      end,
      observed_at=now(),
      raw=coalesce(raw,'{}'::jsonb)||v_payload
  where (source,metric) in (
    ('TEAM_ALIAS_V2','registry'),
    ('TEAM_NAME_MASTER','registry'),
    ('TEAM_ALIAS_REGISTRY_HARDEN','phase1')
  );

  return v_payload || jsonb_build_object('status',v_status);
end
$function$;

CREATE OR REPLACE FUNCTION public.ft_alias_maintenance_v2()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_refresh jsonb;
  v_promote jsonb;
  v_master jsonb;
  v_quarantine jsonb;
  v_registry_harden jsonb;
  v_registry_merge jsonb;
  v_static_consensus jsonb;
  v_reannotate jsonb;
  v_health jsonb;
  v_one_for_all jsonb;
  v_runtime_health jsonb;
  v_women jsonb;
  v_brazil jsonb;
  v_context jsonb;
  v_forebet_queue jsonb;
  v_deferred jsonb;
begin
  v_deferred := public.ft_refresh_deferred_identity_state();
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  v_quarantine := public.ft_apply_team_name_quarantine();
  v_registry_harden := public.ft_promote_registry_from_verified_master();
  v_registry_merge := public.ft_merge_alias_registry_into_team_name_master();
  v_quarantine := v_quarantine || public.ft_apply_team_name_quarantine();
  v_context := public.ft_refresh_static_identity_context();
  v_static_consensus := public.ft_promote_static_master_consensus();
  v_quarantine := v_quarantine || public.ft_apply_team_name_quarantine();

  -- Alias promotions/quarantine can change the correct interpretation of rows
  -- that were ingested earlier in this same cycle. Refresh annotations before
  -- evaluating runtime health so raw telemetry never lags the master registry.
  v_reannotate := private.ft_refresh_multisource_master_annotations();

  v_health := public.ft_record_team_name_master_health();
  v_one_for_all := public.ft_record_one_for_all_alias_health();
  v_women := public.ft_refresh_womens_intl_team_names();
  v_brazil := public.ft_refresh_brazilianfootball_team_names();
  v_forebet_queue := public.ft_record_forebet_identity_queue_health();

  -- Override backlog-oriented registry WARNs with current-impact health.
  -- Historical ambiguous/candidate rows remain in raw metrics and quarantine.
  v_runtime_health := private.ft_record_alias_runtime_health();

  return jsonb_build_object(
    'deferred_identity_state',v_deferred,
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master,
    'quarantine_enforcement',v_quarantine,
    'registry_hardening',v_registry_harden,
    'registry_merge',v_registry_merge,
    'static_identity_context',v_context,
    'static_consensus',v_static_consensus,
    'multisource_reannotation',v_reannotate,
    'team_name_master_health',v_health,
    'one_for_all_health',v_one_for_all,
    'runtime_alias_health',v_runtime_health,
    'forebet_identity_queue',v_forebet_queue,
    'womens_intl_names',v_women,
    'brazilianfootball_names',v_brazil
  );
end
$function$;

CREATE OR REPLACE FUNCTION public.ft_refresh_phase1_coverage_guard()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'private', 'pg_temp'
AS $function$
declare
  v_target_count integer := 0;
  v_missing_availability integer := 0;
  v_forebet_models integer := 0;
  v_fixture_only integer := 0;
  v_source_absent integer := 0;
  v_stale_forebet integer := 0;
  v_zero_evidence integer := 0;
  v_zero_expected_absent integer := 0;
  v_zero_unclassified integer := 0;
  v_missing_ids text[] := array[]::text[];
  v_zero_evidence_ids text[] := array[]::text[];
  v_zero_unclassified_ids text[] := array[]::text[];
  v_status text;
  v_payload jsonb;
begin
  insert into public.forebet_availability (
    hkjc_event_id,checked_at,match_date,kickoff_hkt,league_zh,home_en,away_en,
    state,reason,raw,updated_at
  )
  select
    u.hkjc_event_id,null,
    to_char(u.kickoff_hkt at time zone 'Asia/Hong_Kong','YYYY-MM-DD'),
    u.kickoff_hkt,u.tournament,u.home_en,u.away_en,
    'UNRESOLVED','pending_forebet_refresh_new_hkjc_target',
    jsonb_build_object(
      'materialized_by','ft_refresh_phase1_coverage_guard',
      'pending_real_source_check',true,
      'hkjc_fetched_at',u.fetched_at
    ),
    now()
  from public.hkjc_upcoming_current u
  left join public.forebet_availability fa using(hkjc_event_id)
  where u.fetched_at >= now()-interval '30 minutes'
    and u.selling is true
    and u.kickoff_hkt >= now()
    and u.kickoff_hkt < now()+interval '48 hours'
    and fa.hkjc_event_id is null
  on conflict(hkjc_event_id) do nothing;

  with targets as (
    select u.hkjc_event_id
    from public.hkjc_upcoming_current u
    where u.fetched_at >= now()-interval '30 minutes'
      and u.selling is true
      and u.kickoff_hkt >= now()
      and u.kickoff_hkt < now()+interval '48 hours'
  ),
  coverage as (
    select
      t.hkjc_event_id,
      fa.state forebet_state,
      fa.reason forebet_reason,
      fa.checked_at forebet_checked_at,
      (
        fp.hkjc_event_id is not null
        and fp.prob_home is not null
        and fp.prob_draw is not null
        and fp.prob_away is not null
      ) has_forebet_model,
      coalesce(h.evidence_channel_count,0) evidence_channel_count,
      (
        coalesce(h.evidence_channel_count,0)=0
        and fa.state='UNRESOLVED'
        and fa.reason='forebet_fixture_absent_from_fetched_model_surfaces'
      ) zero_is_expected_source_absence
    from targets t
    left join public.forebet_availability fa using(hkjc_event_id)
    left join public.forebet_predictions fp using(hkjc_event_id)
    left join private.phase1_data_health_current h using(hkjc_event_id)
  )
  select
    count(*)::int,
    count(*) filter(where forebet_state is null)::int,
    count(*) filter(where has_forebet_model)::int,
    count(*) filter(where forebet_state='FIXTURE_ONLY')::int,
    count(*) filter(where forebet_state='UNRESOLVED')::int,
    count(*) filter(
      where forebet_state is not null
        and (forebet_checked_at is null or forebet_checked_at < now()-interval '14 hours')
    )::int,
    count(*) filter(where evidence_channel_count=0)::int,
    count(*) filter(where zero_is_expected_source_absence)::int,
    count(*) filter(where evidence_channel_count=0 and not zero_is_expected_source_absence)::int,
    coalesce(array_agg(hkjc_event_id order by hkjc_event_id)
      filter(where forebet_state is null),array[]::text[]),
    coalesce(array_agg(hkjc_event_id order by hkjc_event_id)
      filter(where evidence_channel_count=0),array[]::text[]),
    coalesce(array_agg(hkjc_event_id order by hkjc_event_id)
      filter(where evidence_channel_count=0 and not zero_is_expected_source_absence),array[]::text[])
  into
    v_target_count,v_missing_availability,v_forebet_models,v_fixture_only,
    v_source_absent,v_stale_forebet,v_zero_evidence,v_zero_expected_absent,
    v_zero_unclassified,v_missing_ids,v_zero_evidence_ids,v_zero_unclassified_ids
  from coverage;

  v_status := case
    when v_missing_availability>0 then 'FAIL'
    when v_stale_forebet>0 or v_zero_unclassified>0 then 'WARN'
    else 'PASS'
  end;

  v_payload := jsonb_build_object(
    'window_hours',48,
    'target_count',v_target_count,
    'missing_forebet_availability',v_missing_availability,
    'forebet_model_count',v_forebet_models,
    'forebet_fixture_only_count',v_fixture_only,
    'forebet_source_absent_count',v_source_absent,
    'stale_forebet_checks',v_stale_forebet,
    'zero_independent_evidence_count',v_zero_evidence,
    'zero_evidence_expected_source_absence_count',v_zero_expected_absent,
    'zero_evidence_unclassified_count',v_zero_unclassified,
    'missing_availability_ids',to_jsonb(v_missing_ids[1:50]),
    'zero_evidence_ids',to_jsonb(v_zero_evidence_ids[1:50]),
    'zero_evidence_unclassified_ids',to_jsonb(v_zero_unclassified_ids[1:50])
  );

  insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
  values(
    'PHASE1_COVERAGE_GUARD','48h',v_payload::text,v_status,
    case
      when v_missing_availability>0 then
        'Canonical HKJC targets still lack an availability row after materialization; upstream recovery required.'
      when v_stale_forebet>0 then
        'Coverage is materialized, but one or more Forebet availability checks are pending or stale.'
      when v_zero_unclassified>0 then
        format('%s current target(s) have no independent evidence without a confirmed source-absence classification.',v_zero_unclassified)
      when v_zero_expected_absent>0 then
        format('Coverage is healthy; %s target(s) are explicitly classified no-data because fetched model surfaces do not contain the fixture.',v_zero_expected_absent)
      when v_target_count=0 then
        'No current HKJC selling targets in the 48h window; guard idle.'
      else
        'Canonical 48h target coverage is classified and independent evidence is available where sources provide it.'
    end,
    now(),v_payload
  )
  on conflict(source,metric) do update set
    value_text=excluded.value_text,status=excluded.status,notes=excluded.notes,
    observed_at=excluded.observed_at,raw=excluded.raw;

  return v_payload||jsonb_build_object('status',v_status);
end
$function$;
revoke all on function private.ft_refresh_multisource_master_annotations() from public;
revoke all on function private.ft_record_alias_runtime_health() from public;

update public.source_health
set status='OK',
    notes='Historical Phase 2 architecture marker; current production owner is api-football-phase2-detail batched worker.',
    raw=coalesce(raw,'{}'::jsonb)||jsonb_build_object('lifecycle','SUPERSEDED','operational',false)
where source='API_FOOTBALL_PHASE2' and metric='architecture';

update public.source_health
set status='OK',
    notes='Football-Data pipeline is operational; lifecycle state ACTIVE is recorded as metadata, not health severity.',
    raw=coalesce(raw,'{}'::jsonb)||jsonb_build_object('lifecycle','ACTIVE')
where source='FOOTBALL_DATA' and metric='pipeline';

update public.source_health
set status='OK',
    notes='Operationally healthy; source is restricted to private-use mode until licensing is re-checked for public/commercial release.',
    raw=coalesce(raw,'{}'::jsonb)||jsonb_build_object('lifecycle','PRIVATE_USE','publish_gate',true)
where source='FOOTBALL_DATA' and metric='private_use_mode';

update public.source_health
set status='OK',
    notes='Historical Phase 2 availability baseline retained for audit; unmapped fixtures are classified unknown/no-data rather than operational failure.',
    raw=coalesce(raw,'{}'::jsonb)||jsonb_build_object('lifecycle','BASELINE_PARTIAL_COVERAGE','operational',false)
where source='PHASE2_LAYER4' and metric='availability_coverage';

update public.source_health
set status='OK',
    notes='Optional Bet365/API-Football odds collector intentionally disabled; API-Football quota is reserved for Phase 2 enrichment.',
    raw=coalesce(raw,'{}'::jsonb)||jsonb_build_object('lifecycle','DISABLED_OPTIONAL','operational',false)
where source='BET365_API_FOOTBALL' and metric='6h';

update public.source_health
set status='OK',
    notes='Optional odds-api framework is not a production dependency and remains disabled until a key/source is intentionally configured.',
    raw=coalesce(raw,'{}'::jsonb)||jsonb_build_object('lifecycle','DISABLED_OPTIONAL','operational',false)
where source='BET365_ODDS_API' and metric='hourly';

update public.source_health
set status='OK',
    value_text='SUPERSEDED_BY_LIVE_LAYER_GUARD',
    notes='Historical freshness audit superseded by LIVE_LAYER_GUARD and LIVE_SHADOW_COMPARE; retained for audit only.',
    raw=coalesce(raw,'{}'::jsonb)||jsonb_build_object('lifecycle','SUPERSEDED','operational',false)
where source='LIVE_FRESHNESS_AUDIT' and metric='live_stats_age_minutes';

update public.source_health
set status='OK',
    notes='Historical queued sync request marker; current canonical sync uses the active batched event-driven path.',
    raw=coalesce(raw,'{}'::jsonb)||jsonb_build_object('lifecycle','HISTORICAL_REQUEST','operational',false)
where source='SUPABASE_SYNC_TRIGGER' and metric in ('current_request','results_request');
