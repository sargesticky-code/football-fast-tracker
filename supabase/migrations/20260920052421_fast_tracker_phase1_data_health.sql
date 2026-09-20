update private.source_registry
set metadata = coalesce(metadata,'{}'::jsonb) || jsonb_build_object(
  'capture_cadence_hours', 12,
  'warn_after_hours', 13,
  'stale_after_hours', 15,
  'freshness_basis', 'fetched_at'
),
updated_at = now()
where source_key='HKJC';

update private.source_registry
set metadata = coalesce(metadata,'{}'::jsonb) || jsonb_build_object(
  'capture_cadence_hours', 24,
  'warn_after_hours', 27,
  'stale_after_hours', 30,
  'freshness_basis', 'checked_or_fetched_at'
),
updated_at = now()
where source_key in ('FOREBET','DC','PI','FORM');

create or replace view private.phase1_data_health_current
with (security_invoker=true)
as
with cfg as (
  select
    coalesce((metadata->>'warn_after_hours')::numeric, 13) as hkjc_warn_hours,
    coalesce((metadata->>'stale_after_hours')::numeric, 15) as hkjc_stale_hours
  from private.source_registry
  where source_key='HKJC'
),
forebet_cfg as (
  select
    coalesce((metadata->>'warn_after_hours')::numeric, 27) as warn_hours,
    coalesce((metadata->>'stale_after_hours')::numeric, 30) as stale_hours
  from private.source_registry
  where source_key='FOREBET'
)
select
  v.hkjc_event_id,
  v.kickoff_hkt,
  v.tournament,
  v.home_en,
  v.away_en,
  v.home_zh,
  v.away_zh,
  v.selling,
  v.status,
  p.fetched_at as hkjc_fetched_at,
  p.odds_updated_at as hkjc_price_changed_at,
  round(extract(epoch from (now()-p.fetched_at))/60.0,1) as hkjc_fetch_age_minutes,
  case
    when p.fetched_at is null then 'MISSING'
    when now()-p.fetched_at > make_interval(hours => cfg.hkjc_stale_hours::int) then 'STALE'
    when now()-p.fetched_at > make_interval(hours => cfg.hkjc_warn_hours::int) then 'AGING'
    else 'FRESH'
  end as hkjc_freshness,
  fa.checked_at as forebet_checked_at,
  fa.state as forebet_state,
  fa.reason as forebet_reason,
  case
    when fa.checked_at is null then 'UNCHECKED'
    when now()-fa.checked_at > make_interval(hours => forebet_cfg.stale_hours::int) then 'STALE'
    when now()-fa.checked_at > make_interval(hours => forebet_cfg.warn_hours::int) then 'AGING'
    else 'FRESH'
  end as forebet_check_freshness,
  mp.quality as internal_model_quality,
  mp.model_source as internal_model_source,
  pf.status as fallback_status,
  pf.source as fallback_source,
  pf.recommendation as fallback_recommendation,
  pf.market as fallback_market,
  exists(
    select 1 from public.team_aliases ta
    where lower(ta.canonical_hkjc_name)=lower(v.home_en)
  ) as home_alias_present,
  exists(
    select 1 from public.team_aliases ta
    where lower(ta.canonical_hkjc_name)=lower(v.away_en)
  ) as away_alias_present,
  ((v.forebet_home is not null)::int
   +(v.dc_home is not null)::int
   +(v.pi_home is not null)::int
   +(v.form_home is not null)::int
   +(v.multisource_home is not null)::int) as evidence_channel_count,
  coalesce(v.multisource_count,0) as multisource_member_count,
  (v.forebet_home is null
   and v.dc_home is null
   and v.pi_home is null
   and v.form_home is null
   and v.multisource_home is null) as missing_canonical_1x2,
  array_remove(array[
    case when fa.checked_at is null then 'FOREBET_NOT_CHECKED' end,
    case when fa.state='UNRESOLVED' then 'FOREBET_UNRESOLVED' end,
    case when fa.state='FIXTURE_ONLY' then 'FOREBET_FIXTURE_ONLY' end,
    case when mp.quality='UNSUPPORTED_HISTORY' then 'INTERNAL_HISTORY_UNSUPPORTED' end,
    case when mp.quality like 'MODEL_FAIL:%' then 'INTERNAL_MODEL_FAIL' end,
    case when pf.status='OK' then 'FALLBACK_MATCHED' end,
    case when pf.status='NO_APWIN_MATCH' then 'FALLBACK_NO_MATCH' end,
    case when not exists(
      select 1 from public.team_aliases ta
      where lower(ta.canonical_hkjc_name)=lower(v.home_en)
    ) then 'HOME_ALIAS_NOT_REGISTERED' end,
    case when not exists(
      select 1 from public.team_aliases ta
      where lower(ta.canonical_hkjc_name)=lower(v.away_en)
    ) then 'AWAY_ALIAS_NOT_REGISTERED' end
  ],null)::text[] as diagnostic_codes,
  case
    when not (
      v.forebet_home is null and v.dc_home is null and v.pi_home is null
      and v.form_home is null and v.multisource_home is null
    ) then null
    when mp.quality like 'MODEL_FAIL:%' then 'MODEL_PIPELINE_FAIL'
    when fa.state='FIXTURE_ONLY' then 'FOREBET_FIXTURE_NO_PREDICTION'
    when pf.status='OK' then 'FALLBACK_ONLY_NON_1X2'
    when fa.state='UNRESOLVED'
      and mp.quality='UNSUPPORTED_HISTORY'
      and pf.status='NO_APWIN_MATCH' then 'MULTI_SOURCE_UNRESOLVED'
    when fa.checked_at is null then 'SOURCE_SCAN_NOT_RECORDED'
    when mp.quality='UNSUPPORTED_HISTORY' then 'HISTORY_UNSUPPORTED'
    else 'NO_CANONICAL_1X2_EVIDENCE'
  end as primary_missing_reason,
  case
    when p.fetched_at is null then 'ATTENTION'
    when now()-p.fetched_at > make_interval(hours => cfg.hkjc_stale_hours::int) then 'ATTENTION'
    when v.forebet_home is null and v.dc_home is null and v.pi_home is null
      and v.form_home is null and v.multisource_home is null then 'MISSING_EVIDENCE'
    else 'OK'
  end as health_status
from api.phase1_match_intelligence_v v
cross join cfg
cross join forebet_cfg
left join public.hkjc_odds_current p using(hkjc_event_id)
left join public.forebet_availability fa using(hkjc_event_id)
left join public.model_predictions mp using(hkjc_event_id)
left join public.prediction_fallback_current pf using(hkjc_event_id);

revoke all on private.phase1_data_health_current from public, anon, authenticated;
grant select on private.phase1_data_health_current to service_role;

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
  ),
  rows as (
    select
      v.hkjc_event_id,
      v.kickoff_hkt,
      to_jsonb(v) || jsonb_build_object(
        'health_status', h.health_status,
        'primary_missing_reason', h.primary_missing_reason,
        'diagnostic_codes', h.diagnostic_codes,
        'hkjc_fetched_at', h.hkjc_fetched_at,
        'hkjc_price_changed_at', h.hkjc_price_changed_at,
        'hkjc_fetch_age_minutes', h.hkjc_fetch_age_minutes,
        'hkjc_freshness', h.hkjc_freshness,
        'forebet_checked_at', h.forebet_checked_at,
        'forebet_state', h.forebet_state,
        'forebet_reason', h.forebet_reason,
        'forebet_check_freshness', h.forebet_check_freshness,
        'internal_model_quality', h.internal_model_quality,
        'internal_model_source', h.internal_model_source,
        'fallback_status', h.fallback_status,
        'fallback_source', h.fallback_source,
        'fallback_recommendation', h.fallback_recommendation,
        'fallback_market', h.fallback_market,
        'home_alias_present', h.home_alias_present,
        'away_alias_present', h.away_alias_present,
        'evidence_channel_count', h.evidence_channel_count,
        'multisource_member_count', h.multisource_member_count,
        'missing_canonical_1x2', h.missing_canonical_1x2
      ) as payload
    from api.phase1_match_intelligence_v v
    cross join bounds b
    left join private.phase1_data_health_current h using(hkjc_event_id)
    where v.selling is true
      and v.kickoff_hkt >= b.starts_at
      and v.kickoff_hkt < b.ends_at
  )
  select coalesce(
    jsonb_agg(payload order by kickoff_hkt, hkjc_event_id),
    '[]'::jsonb
  )
  from rows;
$$;

revoke all on function public.ft_internal_app_phase1_feed(integer) from public;
revoke all on function public.ft_internal_app_phase1_feed(integer) from anon;
revoke all on function public.ft_internal_app_phase1_feed(integer) from authenticated;
grant execute on function public.ft_internal_app_phase1_feed(integer) to service_role;
