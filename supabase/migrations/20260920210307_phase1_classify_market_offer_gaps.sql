create or replace view public.phase1_hkjc_market_authority_health_v as
select
  u.hkjc_event_id,u.match_id,u.kickoff_hkt,u.home_zh,u.away_zh,u.selling,
  u.fetched_at as authority_fetched_at,u.odds_updated_at as authority_odds_updated_at,
  o.fetched_at as legacy_odds_fetched_at,o.odds_updated_at as legacy_odds_updated_at,
  (u.had_home is not null and u.had_draw is not null and u.had_away is not null) as had_complete,
  (u.hil_line is not null and u.hil_over is not null and u.hil_under is not null) as goals_complete,
  (u.chl_line is not null and u.chl_over is not null and u.chl_under is not null) as corners_complete,
  (o.hkjc_event_id is not null) as legacy_odds_joined,
  case when o.hkjc_event_id is null then null::boolean else (u.had_home is distinct from o.had_home or u.had_draw is distinct from o.had_draw or u.had_away is distinct from o.had_away) end as legacy_had_diff,
  case when o.hkjc_event_id is null then null::boolean else (u.hil_line is distinct from o.hil_line or u.hil_over is distinct from o.hil_over or u.hil_under is distinct from o.hil_under) end as legacy_goals_diff,
  case when o.hkjc_event_id is null then null::boolean else (u.chl_line is distinct from o.chl_line or u.chl_over is distinct from o.chl_over or u.chl_under is distinct from o.chl_under) end as legacy_corners_diff,
  extract(epoch from now()-u.fetched_at)/60.0 as authority_age_minutes,
  case when o.fetched_at is null then null::numeric else extract(epoch from now()-o.fetched_at)/60.0 end as legacy_odds_age_minutes,
  case when u.fetched_at is null then 'NO_AUTHORITY_TIMESTAMP' when now()-u.fetched_at>interval '30 minutes' then 'STALE_AUTHORITY' when coalesce(u.raw->'sellingPools' ? 'HAD',false) and not (u.had_home is not null and u.had_draw is not null and u.had_away is not null) then 'HAD_CAPTURE_GAP' when coalesce(u.raw->'sellingPools' ? 'HIL',false) and not (u.hil_line is not null and u.hil_over is not null and u.hil_under is not null) then 'GOALS_CAPTURE_GAP' when coalesce(u.raw->'sellingPools' ? 'CHL',false) and not (u.chl_line is not null and u.chl_over is not null and u.chl_under is not null) then 'CORNERS_CAPTURE_GAP' else 'OK' end as authority_health,
  coalesce(u.raw->'sellingPools' ? 'HAD',false) as had_offered,
  coalesce(u.raw->'sellingPools' ? 'HIL',false) as goals_offered,
  coalesce(u.raw->'sellingPools' ? 'CHL',false) as corners_offered,
  case when coalesce(u.raw->'sellingPools' ? 'HAD',false) and not (u.had_home is not null and u.had_draw is not null and u.had_away is not null) then 'CAPTURE_GAP' when not coalesce(u.raw->'sellingPools' ? 'HAD',false) then 'NOT_OFFERED' else 'OK' end as had_market_state,
  case when coalesce(u.raw->'sellingPools' ? 'HIL',false) and not (u.hil_line is not null and u.hil_over is not null and u.hil_under is not null) then 'CAPTURE_GAP' when not coalesce(u.raw->'sellingPools' ? 'HIL',false) then 'NOT_OFFERED' else 'OK' end as goals_market_state,
  case when coalesce(u.raw->'sellingPools' ? 'CHL',false) and not (u.chl_line is not null and u.chl_over is not null and u.chl_under is not null) then 'CAPTURE_GAP' when not coalesce(u.raw->'sellingPools' ? 'CHL',false) then 'NOT_OFFERED' else 'OK' end as corners_market_state
from public.hkjc_upcoming_current u left join public.hkjc_odds_current o using(hkjc_event_id)
where u.selling is true and u.kickoff_hkt>now();
