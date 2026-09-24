create or replace view public.phase1_forebet_coverage_health_v as
with upcoming as (
  select hkjc_event_id,kickoff_hkt,tournament,home_en,away_en
  from public.hkjc_upcoming_current
  where selling is true and kickoff_hkt > now() and kickoff_hkt <= now()+interval '48 hours'
), pred as (
  select distinct on (hkjc_event_id) hkjc_event_id,fetched_at,match_score
  from public.forebet_predictions order by hkjc_event_id,fetched_at desc
), avail as (
  select distinct on (hkjc_event_id) hkjc_event_id,checked_at,state,reason
  from public.forebet_availability order by hkjc_event_id,checked_at desc
)
select u.*,
       p.fetched_at as prediction_fetched_at,
       a.checked_at as diagnostic_checked_at,
       case
         when p.hkjc_event_id is not null then 'MODEL_AVAILABLE'
         when a.hkjc_event_id is null then 'DIAGNOSTIC_MISSING'
         when now()-a.checked_at > interval '90 minutes' then 'DIAGNOSTIC_STALE'
         when a.reason='forebet_source_surface_unavailable' then 'SOURCE_SURFACE_GAP'
         when a.reason='target_missing_from_forebet_scan_output' then 'SCAN_COVERAGE_GAP'
         when a.state='FIXTURE_ONLY' then 'FIXTURE_ONLY'
         else 'DIAGNOSED_OTHER_GAP'
       end as coverage_health,
       a.state as availability_state,a.reason as availability_reason
from upcoming u left join pred p using(hkjc_event_id) left join avail a using(hkjc_event_id);
