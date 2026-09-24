
create or replace view public.live_shadow_compare_v
with (security_invoker=true)
as
select
  l.hkjc_event_id,
  l.fetched_at as hkjc_live_at,
  s.updated_at_source as production_score_at,
  sh.captured_at as shadow_at,
  s.source as production_source,
  s.source_match_id as production_source_match_id,
  sh.source as shadow_source,
  sh.source_match_id as shadow_source_match_id,
  s.home_score as production_home_score,
  s.away_score as production_away_score,
  sh.home_score as shadow_home_score,
  sh.away_score as shadow_away_score,
  s.minute as production_minute,
  sh.minute as shadow_minute,
  d.detail_status as shadow_detail_status,
  case
    when sh.hkjc_event_id is null then false
    when coalesce(sh.source,'')='SOURCE_GAP' then false
    when sh.source_match_id is null or sh.source_match_id='' then false
    else true
  end as shadow_present,
  case
    when sh.hkjc_event_id is null then null
    when coalesce(sh.source,'')='SOURCE_GAP' then null
    when s.source_match_id is null or sh.source_match_id is null then null
    else s.source_match_id=sh.source_match_id
  end as source_id_match,
  case
    when sh.hkjc_event_id is null then null
    when coalesce(sh.source,'')='SOURCE_GAP' then null
    when s.home_score is null or s.away_score is null or sh.home_score is null or sh.away_score is null then null
    else s.home_score=sh.home_score and s.away_score=sh.away_score
  end as score_match,
  case
    when sh.hkjc_event_id is null then null
    when coalesce(sh.source,'')='SOURCE_GAP' then null
    when s.minute is null or sh.minute is null then null
    else abs(s.minute-sh.minute)
  end as minute_delta
from public.hkjc_live_odds_current l
left join public.live_score_current s using(hkjc_event_id)
left join public.live_source_shadow_current sh using(hkjc_event_id)
left join public.live_detail_shadow_current d using(hkjc_event_id)
where l.fetched_at>=now()-interval '3 minutes';

select public.ft_refresh_live_shadow_compare_guard();
