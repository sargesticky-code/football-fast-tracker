create or replace view public.phase1_forebet_fixture_only_diagnostic with (security_invoker=true) as
select
  q.last_event_id as hkjc_event_id,
  q.tournament,
  q.hkjc_name_en,
  q.reason as queue_reason,
  q.occurrence_count,
  a.source_competition,
  a.source_home_team,
  a.source_away_team,
  a.identity_status,
  a.fixture_match_score,
  e.forebet_status,
  e.source_updated_at,
  case
    when e.hkjc_event_id is not null
     and e.forebet_status='FIXTURE_ONLY'
     and e.prob_home is null and e.prob_draw is null and e.prob_away is null
     and e.predicted_score is null and e.avg_goals is null
    then 'PROVIDER_FIXTURE_ONLY_NO_PREDICTION_PUBLISHED'
    when e.hkjc_event_id is not null
     and (e.prob_home is not null or e.prob_draw is not null or e.prob_away is not null or e.predicted_score is not null or e.avg_goals is not null)
    then 'MODEL_PRESENT'
    else 'MODEL_SURFACE_NOT_PRESENT'
  end as diagnostic_class
from public.team_alias_gap_queue_v2 q
left join public.forebet_availability a on a.hkjc_event_id=q.last_event_id
left join public.forebet_effective_v e on e.hkjc_event_id=q.last_event_id
where q.source='FOREBET';

comment on view public.phase1_forebet_fixture_only_diagnostic is 'Phase 1 diagnostic: distinguishes Forebet fixture-only rows with no provider-published prediction fields from parser/model-present cases. Prevents treating provider fixture-only coverage as an alias or parser defect.';
