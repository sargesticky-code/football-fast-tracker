create or replace view public.live_expected_actual_current
with (security_invoker=true)
as
with eligible_live as (
  select
    l.hkjc_event_id,
    l.status as hkjc_live_status,
    l.fetched_at as live_market_fetched_at,
    l.pool_status,
    s.captured_at_hkt,
    s.match_minute,
    s.live_score,
    s.match_status,
    s.source,
    s.match_confidence,
    s.team_stats,
    case
      when coalesce(s.match_minute,0) <= 15 then '0-15'
      when s.match_minute <= 30 then '16-30'
      when s.match_minute <= 45 then '31-HT'
      when s.match_minute <= 60 then '46-60'
      when s.match_minute <= 75 then '61-75'
      else '76-FT'
    end as segment
  from public.hkjc_live_odds_current l
  join public.live_stats_current s using(hkjc_event_id)
  where l.pool_status='SELLINGSTARTED'
    and l.fetched_at >= now()-interval '10 minutes'
    and s.captured_at_hkt >= now()-interval '10 minutes'
    and coalesce(s.match_confidence,0) >= 0.74
    and upper(coalesce(l.status,'')) not in
      ('PREEVENT','MATCHENDED','INPLAYMATCHENDED','FULLTIME','FINISHED','FT','ENDED')
),
stats as (
  select
    e.*,
    xg.home xg_home, xg.away xg_away,
    shots.home shots_home, shots.away shots_away,
    sot.home sot_home, sot.away sot_away,
    poss.home possession_home, poss.away possession_away,
    box.home box_touches_home, box.away box_touches_away,
    big.home big_chances_home, big.away big_chances_away,
    cor.home corners_home, cor.away corners_away
  from eligible_live e
  left join lateral (
    select nullif(x->>'home','')::numeric home, nullif(x->>'away','')::numeric away
    from jsonb_array_elements(coalesce(e.team_stats,'[]'::jsonb)) x
    where x->>'key'='expected_goals' and x->>'period'='All'
      and (x->>'home' is not null or x->>'away' is not null)
    order by ((x->>'home') is null and (x->>'away') is null)
    limit 1
  ) xg on true
  left join lateral (
    select nullif(x->>'home','')::numeric home, nullif(x->>'away','')::numeric away
    from jsonb_array_elements(coalesce(e.team_stats,'[]'::jsonb)) x
    where x->>'key'='total_shots' and x->>'period'='All'
    limit 1
  ) shots on true
  left join lateral (
    select nullif(x->>'home','')::numeric home, nullif(x->>'away','')::numeric away
    from jsonb_array_elements(coalesce(e.team_stats,'[]'::jsonb)) x
    where x->>'key'='shotsontarget' and x->>'period'='All'
    limit 1
  ) sot on true
  left join lateral (
    select nullif(x->>'home','')::numeric home, nullif(x->>'away','')::numeric away
    from jsonb_array_elements(coalesce(e.team_stats,'[]'::jsonb)) x
    where x->>'key'='ballpossesion' and x->>'period'='All'
    limit 1
  ) poss on true
  left join lateral (
    select nullif(x->>'home','')::numeric home, nullif(x->>'away','')::numeric away
    from jsonb_array_elements(coalesce(e.team_stats,'[]'::jsonb)) x
    where x->>'key'='touches_opp_box' and x->>'period'='All'
    limit 1
  ) box on true
  left join lateral (
    select nullif(x->>'home','')::numeric home, nullif(x->>'away','')::numeric away
    from jsonb_array_elements(coalesce(e.team_stats,'[]'::jsonb)) x
    where x->>'key'='big_chance' and x->>'period'='All'
    limit 1
  ) big on true
  left join lateral (
    select nullif(x->>'home','')::numeric home, nullif(x->>'away','')::numeric away
    from jsonb_array_elements(coalesce(e.team_stats,'[]'::jsonb)) x
    where x->>'key'='corners' and x->>'period'='All'
    limit 1
  ) cor on true
),
scored as (
  select
    s.*,
    sc.macro_control_side as expected_control_side,
    sc.control_basis,
    sc.context_coverage_score,
    sc.model_hda_consensus,
    (
      case when xg_home is not null and xg_away is not null
        then case when xg_home-xg_away >= 0.25 then 2 when xg_away-xg_home >= 0.25 then -2 else 0 end
        else 0 end
      +
      case when shots_home is not null and shots_away is not null
        then case when shots_home-shots_away >= 3 then 1 when shots_away-shots_home >= 3 then -1 else 0 end
        else 0 end
      +
      case when sot_home is not null and sot_away is not null
        then case when sot_home-sot_away >= 2 then 1 when sot_away-sot_home >= 2 then -1 else 0 end
        else 0 end
      +
      case when possession_home is not null and possession_away is not null
        then case when possession_home-possession_away >= 8 then 1 when possession_away-possession_home >= 8 then -1 else 0 end
        else 0 end
      +
      case when box_touches_home is not null and box_touches_away is not null
        then case when box_touches_home-box_touches_away >= 5 then 1 when box_touches_away-box_touches_home >= 5 then -1 else 0 end
        else 0 end
      +
      case when big_chances_home is not null and big_chances_away is not null
        then case when big_chances_home-big_chances_away >= 1 then 1 when big_chances_away-big_chances_home >= 1 then -1 else 0 end
        else 0 end
      +
      case when corners_home is not null and corners_away is not null
        then case when corners_home-corners_away >= 2 then 1 when corners_away-corners_home >= 2 then -1 else 0 end
        else 0 end
    )::integer as actual_control_score,
    (
      (xg_home is not null and xg_away is not null)::int +
      (shots_home is not null and shots_away is not null)::int +
      (sot_home is not null and sot_away is not null)::int +
      (possession_home is not null and possession_away is not null)::int +
      (box_touches_home is not null and box_touches_away is not null)::int +
      (big_chances_home is not null and big_chances_away is not null)::int +
      (corners_home is not null and corners_away is not null)::int
    )::integer as live_metric_count
  from stats s
  left join public.match_scenario_current sc
    on sc.hkjc_event_id=s.hkjc_event_id and sc.segment=s.segment
),
classified as (
  select *,
    case
      when actual_control_score >= 2 then 'H'
      when actual_control_score <= -2 then 'A'
      else 'BALANCED'
    end as actual_control_side
  from scored
)
select
  hkjc_event_id,
  segment,
  match_minute,
  live_score,
  hkjc_live_status,
  expected_control_side,
  actual_control_side,
  actual_control_score,
  live_metric_count,
  control_basis,
  context_coverage_score,
  model_hda_consensus,
  case
    when expected_control_side is null or expected_control_side='UNKNOWN' then 'WAIT'
    when coalesce(match_minute,0) < 10 then 'WAIT'
    when live_metric_count < 3 then 'WAIT'
    when actual_control_side='BALANCED' then 'WAIT'
    when actual_control_side=expected_control_side then 'CONFIRM'
    else 'CONTRADICT'
  end as shadow_status,
  case
    when expected_control_side is null or expected_control_side='UNKNOWN' then 'NO_EXPECTED_CONTROL'
    when coalesce(match_minute,0) < 10 then 'EARLY_MATCH'
    when live_metric_count < 3 then 'INSUFFICIENT_LIVE_METRICS'
    when actual_control_side='BALANCED' then 'LIVE_CONTROL_BALANCED'
    when actual_control_side=expected_control_side then 'LIVE_CONTROL_ALIGNS'
    else 'LIVE_CONTROL_OPPOSES'
  end as shadow_reason,
  xg_home,xg_away,
  shots_home,shots_away,
  sot_home,sot_away,
  possession_home,possession_away,
  box_touches_home,box_touches_away,
  big_chances_home,big_chances_away,
  corners_home,corners_away,
  captured_at_hkt,
  live_market_fetched_at,
  source,
  match_confidence
from classified;
