create or replace view public.phase1_model_form_identity_health_v as
select
  u.hkjc_event_id,
  u.match_id,
  u.kickoff_hkt,
  u.home_en as hkjc_home_en,
  u.away_en as hkjc_away_en,
  (mp.hkjc_event_id is not null) as model_present,
  mp.model_source,
  mp.team_match_quality,
  case
    when mp.hkjc_event_id is null then 'NO_SOURCE_ROW'
    when lower(trim(mp.home)) = lower(trim(u.home_en))
     and lower(trim(mp.away)) = lower(trim(u.away_en))
     and coalesce(mp.team_match_quality,0) >= 0.90 then 'IDENTITY_OK'
    else 'FAIL_CLOSED'
  end as model_identity_status,
  (fp.hkjc_event_id is not null) as form_present,
  fp.model_source as form_source,
  case
    when fp.hkjc_event_id is null then 'NO_SOURCE_ROW'
    when lower(trim(fp.home)) = lower(trim(u.home_en))
     and lower(trim(fp.away)) = lower(trim(u.away_en)) then 'IDENTITY_OK'
    else 'FAIL_CLOSED'
  end as form_identity_status
from public.hkjc_upcoming_current u
left join public.model_predictions mp using (hkjc_event_id)
left join public.form_predictions fp using (hkjc_event_id)
where u.selling is true
  and u.kickoff_hkt > now()
  and u.kickoff_hkt <= now() + interval '48 hours';
