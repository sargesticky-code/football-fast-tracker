drop view if exists public.phase1_identity_gap_classification;
create view public.phase1_identity_gap_classification with (security_invoker=true) as
select q.source,q.team_key,q.hkjc_name_en,q.hkjc_name_zh,q.last_event_id,q.tournament,q.reason,q.occurrence_count,q.first_seen_at,q.last_seen_at,
  case
    when q.reason in ('forebet_alias_near_miss_review','forebet_match_policy_review') and coalesce(fq.queue_reason,'')='SOURCE_FIXTURE_NOT_OBSERVED' then 'SOURCE_ABSENCE_OR_MODEL_ABSENCE'
    when q.reason='current_model_missing_after_reconcile' and exists (select 1 from public.team_name_master m where m.team_key=q.team_key and m.status='VERIFIED') then 'RECONCILE_OR_MODEL_GAP'
    when q.reason in ('forebet_alias_near_miss_review','forebet_match_policy_review','current_model_missing_after_reconcile') then 'IDENTITY_OR_RECONCILE_GAP'
    when q.reason in ('forebet_source_surface_unavailable','forebet_fixture_absent_from_fetched_model_surfaces','previously_observed_forebet_fixture_without_prediction_model','not_resolved_on_forebet_prediction_or_livescore_surfaces','forebet_livescore_fixture_without_usable_prediction_model') then 'SOURCE_ABSENCE_OR_MODEL_ABSENCE'
    else 'REVIEW_REQUIRED' end as gap_class,
  exists (select 1 from public.team_name_master m where m.team_key=q.team_key and m.status='VERIFIED') as has_verified_static_identity,
  fq.queue_reason as provider_surface_reason
from public.team_alias_gap_queue_v2 q
left join public.forebet_identity_candidate_queue_v fq on upper(q.source)='FOREBET' and fq.hkjc_event_id=q.last_event_id;
