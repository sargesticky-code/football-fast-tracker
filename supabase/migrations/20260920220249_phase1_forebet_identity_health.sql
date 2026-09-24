create or replace view public.phase1_forebet_identity_health_v as
with cur as (
  select hkjc_event_id,kickoff_hkt,tournament,home_en,away_en,home_zh,away_zh
  from public.hkjc_upcoming_current
  where selling=true and kickoff_hkt>now() and kickoff_hkt<=now()+interval '48 hours'
), f as (
  select hkjc_event_id,forebet_home_team,forebet_away_team,match_score,fetched_at
  from public.forebet_predictions
), joined as (
 select c.*,f.forebet_home_team,f.forebet_away_team,f.match_score,f.fetched_at,
   ah.canonical_hkjc_name as home_alias_canonical, ah.confidence as home_alias_confidence, ah.status as home_alias_status,
   aa.canonical_hkjc_name as away_alias_canonical, aa.confidence as away_alias_confidence, aa.status as away_alias_status
 from cur c left join f using(hkjc_event_id)
 left join public.team_aliases ah on upper(ah.source)='FOREBET' and lower(trim(ah.alias))=lower(trim(f.forebet_home_team)) and ah.status in ('ACTIVE','MANUAL')
 left join public.team_aliases aa on upper(aa.source)='FOREBET' and lower(trim(aa.alias))=lower(trim(f.forebet_away_team)) and aa.status in ('ACTIVE','MANUAL')
)
select *,
 case
  when forebet_home_team is null or forebet_away_team is null then 'NO_FOREBET_FIXTURE'
  when match_score is null or match_score < 0.90 then 'FAIL_WEAK_MATCH'
  when lower(trim(forebet_home_team))=lower(trim(home_en)) then 'EXACT'
  when home_alias_canonical is not null and lower(trim(home_alias_canonical))=lower(trim(home_en)) and home_alias_confidence>=0.90 then 'ALIAS_OK'
  else 'FAIL_HOME_IDENTITY'
 end as home_identity_state,
 case
  when forebet_home_team is null or forebet_away_team is null then 'NO_FOREBET_FIXTURE'
  when match_score is null or match_score < 0.90 then 'FAIL_WEAK_MATCH'
  when lower(trim(forebet_away_team))=lower(trim(away_en)) then 'EXACT'
  when away_alias_canonical is not null and lower(trim(away_alias_canonical))=lower(trim(away_en)) and away_alias_confidence>=0.90 then 'ALIAS_OK'
  else 'FAIL_AWAY_IDENTITY'
 end as away_identity_state,
 case
  when forebet_home_team is null or forebet_away_team is null then 'NO_FOREBET_FIXTURE'
  when match_score is null or match_score < 0.90 then 'FAIL_WEAK_MATCH'
  when not (lower(trim(forebet_home_team))=lower(trim(home_en)) or (home_alias_canonical is not null and lower(trim(home_alias_canonical))=lower(trim(home_en)) and home_alias_confidence>=0.90)) then 'FAIL_CLOSED'
  when not (lower(trim(forebet_away_team))=lower(trim(away_en)) or (away_alias_canonical is not null and lower(trim(away_alias_canonical))=lower(trim(away_en)) and away_alias_confidence>=0.90)) then 'FAIL_CLOSED'
  else 'IDENTITY_OK'
 end as identity_health
from joined;
