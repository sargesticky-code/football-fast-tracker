-- Phase 1 / App Core only.
-- Current HKJC anchor replay telemetry for Forebet static-master coverage.
-- Important: fetched-surface absence is NOT treated as proven provider/source absence.

create or replace view public.phase1_current_forebet_anchor_replay_v as
with anchors as (
  select hkjc_event_id,kickoff_hkt,tournament,home_en,away_en
  from public.hkjc_upcoming_current
), fp as (
  select distinct on (hkjc_event_id)
    hkjc_event_id,forebet_league_short,forebet_home_team,forebet_away_team,fetched_at
  from public.forebet_predictions
  order by hkjc_event_id,fetched_at desc
), fa as (
  select distinct hkjc_event_id from public.forebet_archive
), fs as (
  select distinct hkjc_event_id from public.forebet_supplement
), av as (
  select distinct on (hkjc_event_id) hkjc_event_id,state,reason,checked_at
  from public.forebet_availability
  order by hkjc_event_id,checked_at desc
)
select a.*,
  fp.forebet_league_short,fp.forebet_home_team,fp.forebet_away_team,
  fp.fetched_at as provider_fetched_at,
  mh.team_key as home_team_key,ma.team_key as away_team_key,
  case
    when fp.hkjc_event_id is not null and mh.team_key is not null and ma.team_key is not null then 'DIRECT_MASTER'
    when fp.hkjc_event_id is not null then 'NAME_LEAGUE_MATCH_GAP'
    when fa.hkjc_event_id is not null or fs.hkjc_event_id is not null then 'PROVIDER_ARCHIVE_OR_SUPPLEMENT_ONLY'
    else 'FETCHED_SURFACE_ABSENT_NOT_PROVEN_SOURCE_ABSENT'
  end as identity_coverage_class,
  av.state as availability_state,av.reason as availability_reason,
  av.checked_at as availability_checked_at
from anchors a
left join fp using(hkjc_event_id)
left join fa using(hkjc_event_id)
left join fs using(hkjc_event_id)
left join av using(hkjc_event_id)
left join public.team_name_master mh
  on mh.source='FOREBET' and mh.source_name=fp.forebet_home_team and mh.status='VERIFIED'
left join public.team_name_master ma
  on ma.source='FOREBET' and ma.source_name=fp.forebet_away_team and ma.status='VERIFIED';

comment on view public.phase1_current_forebet_anchor_replay_v is
'Phase 1 current HKJC anchor replay telemetry. Distinguishes direct static-master identity, provider-present identity gaps, archive/supplement-only evidence, and fetched-surface absence. Fetched-surface absence is intentionally not labelled true provider absence.';
