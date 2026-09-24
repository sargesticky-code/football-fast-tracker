
create or replace view private.phase1_repair_queue_current
with (security_invoker=true)
as
select
  h.hkjc_event_id,
  h.kickoff_hkt,
  h.tournament,
  h.home_en,
  h.away_en,
  h.home_zh,
  h.away_zh,
  h.primary_missing_reason,
  h.diagnostic_codes,
  h.hkjc_freshness,
  h.forebet_state,
  h.forebet_reason,
  h.internal_model_quality,
  h.internal_model_source,
  h.fallback_status,
  h.fallback_source,
  h.home_alias_present,
  h.away_alias_present,
  case h.primary_missing_reason
    when 'SOURCE_SCAN_NOT_RECORDED' then 'P0'
    when 'MODEL_PIPELINE_FAIL' then 'P1'
    when 'MULTI_SOURCE_UNRESOLVED' then 'P1'
    when 'FOREBET_FIXTURE_NO_PREDICTION' then 'P2'
    when 'FALLBACK_ONLY_NON_1X2' then 'P2'
    else 'P2'
  end as repair_priority,
  case h.primary_missing_reason
    when 'SOURCE_SCAN_NOT_RECORDED'
      then 'Ensure every HKJC selling HAD target enters the source-availability scan on each scheduled capture.'
    when 'MODEL_PIPELINE_FAIL'
      then 'Fix model fallback coverage: build HKJC stable team-id/history mapping from all HKJC selling HAD targets, not only Forebet-covered matches.'
    when 'MULTI_SOURCE_UNRESOLVED'
      then 'Reconcile source coverage and matching; preserve unresolved state until a source provides confident fixture/model evidence.'
    when 'FOREBET_FIXTURE_NO_PREDICTION'
      then 'Treat as genuine source limitation unless another independent model can provide evidence.'
    when 'FALLBACK_ONLY_NON_1X2'
      then 'Keep fallback evidence separate; do not promote non-1X2 recommendation into canonical 1X2 probability.'
    else 'Investigate source coverage without guessing or fuzzy-promoting a match.'
  end as repair_action
from private.phase1_data_health_current h
where h.selling is true
  and h.missing_canonical_1x2 is true;

revoke all on private.phase1_repair_queue_current from public, anon, authenticated;
grant select on private.phase1_repair_queue_current to service_role;
