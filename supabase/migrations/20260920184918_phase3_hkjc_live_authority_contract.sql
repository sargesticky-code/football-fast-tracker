create or replace view public.phase3_hkjc_live_authority_v as
with latest as (
  select max(fetched_at) as authority_fetched_at
  from public.hkjc_live_odds_current
), rows as (
  select h.*, l.authority_fetched_at,
         extract(epoch from (now() - l.authority_fetched_at))::integer as authority_age_seconds
  from public.hkjc_live_odds_current h
  cross join latest l
  where h.fetched_at = l.authority_fetched_at
)
select
  hkjc_event_id,
  match_id,
  kickoff_hkt,
  tournament,
  home_en, away_en, home_zh, away_zh,
  status,
  pool_status,
  authority_fetched_at,
  authority_age_seconds,
  case
    when authority_fetched_at is null then 'NO_SNAPSHOT'
    when authority_age_seconds > 300 then 'STALE_AUTHORITY'
    when upper(coalesce(pool_status,'')) <> 'SELLINGSTARTED' then 'NOT_SELLING'
    when upper(coalesce(status,'')) not in ('FIRSTHALF','SECONDHALF','HALFTIME','LIVE','INPLAY') then 'NOT_LIVE'
    else 'ELIGIBLE'
  end as authority_state,
  (authority_age_seconds <= 300
   and upper(coalesce(pool_status,'')) = 'SELLINGSTARTED'
   and upper(coalesce(status,'')) in ('FIRSTHALF','SECONDHALF','HALFTIME','LIVE','INPLAY')) as eligible,
  had_home, had_draw, had_away,
  hil_line, hil_over, hil_under,
  chl_line, chl_over, chl_under,
  odds_updated_at,
  raw
from rows;

comment on view public.phase3_hkjc_live_authority_v is
'Phase 3-only HKJC live authority. Eligibility requires latest snapshot, <=300s freshness, SELLINGSTARTED and live match status. odds_updated_at is market metadata only and never determines live eligibility.';
