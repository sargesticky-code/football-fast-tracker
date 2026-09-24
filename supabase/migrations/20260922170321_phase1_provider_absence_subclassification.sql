create or replace view public.phase1_identity_gap_classification_v2 with (security_invoker=true) as
select g.*,
case
 when g.gap_class='RESOLVED_CURRENT_MODEL_PRESENT' then 'RESOLVED'
 when g.gap_class<>'SOURCE_ABSENCE_OR_MODEL_ABSENCE' then g.gap_class
 when g.provider_surface_reason='SOURCE_FIXTURE_NOT_OBSERVED' then 'PROVIDER_FIXTURE_NOT_OBSERVED'
 when g.reason='previously_observed_forebet_fixture_without_prediction_model' then 'PROVIDER_FIXTURE_OBSERVED_NO_MODEL'
 when g.reason='forebet_livescore_fixture_without_usable_prediction_model' then 'PROVIDER_FIXTURE_OBSERVED_NO_USABLE_MODEL'
 when g.reason='forebet_source_surface_unavailable' then 'PROVIDER_SURFACE_UNAVAILABLE'
 when g.reason='forebet_fixture_absent_from_fetched_model_surfaces' then 'PROVIDER_FIXTURE_NOT_IN_FETCHED_MODEL_SURFACE'
 when g.reason='not_resolved_on_forebet_prediction_or_livescore_surfaces' then 'PROVIDER_FIXTURE_NOT_OBSERVED'
 else 'SOURCE_MODEL_REVIEW'
end as absence_class
from public.phase1_identity_gap_classification g;
