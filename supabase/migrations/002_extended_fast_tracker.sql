-- Extended Fast Tracker schema: secondary feeds + Sheet formula logic.

create table if not exists public.forebet_supplement (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  fetched_at timestamptz,
  kickoff_hkt timestamptz,
  hkjc_league text,
  home_en text,
  away_en text,
  prob_home numeric,
  prob_draw numeric,
  prob_away numeric,
  prediction_1x2 text,
  predicted_score text,
  avg_goals numeric,
  source_url text,
  match_score numeric,
  status text,
  notes text,
  prediction_ou25 text,
  prob_over25 numeric,
  prob_under25 numeric,
  ou_predicted_score text,
  corner_prediction text,
  corner_prob_under95 numeric,
  corner_prob_over95 numeric,
  corner_predicted_score text,
  avg_corners numeric,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.forebet_archive (
  hkjc_event_id text not null references public.matches(hkjc_event_id) on delete cascade,
  captured_at timestamptz not null,
  hkjc_league text,
  hkjc_home_team text,
  hkjc_away_team text,
  hkjc_home_zh text,
  hkjc_away_zh text,
  hkjc_kickoff_hkt timestamptz,
  prob_home numeric,
  prob_draw numeric,
  prob_away numeric,
  prediction_1x2 text,
  predicted_score text,
  avg_goals numeric,
  power_home numeric,
  power_away numeric,
  power_source text,
  power_updated timestamptz,
  prediction_ou25 text,
  prob_over25 numeric,
  prob_under25 numeric,
  ou_predicted_score text,
  corner_prediction text,
  corner_prob_under95 numeric,
  corner_prob_over95 numeric,
  corner_predicted_score text,
  avg_corners numeric,
  forebet_detail_url text,
  raw jsonb not null default '{}'::jsonb,
  primary key (hkjc_event_id, captured_at)
);

create index if not exists forebet_archive_event_time_idx
  on public.forebet_archive (hkjc_event_id, captured_at desc);

create table if not exists public.forebet_availability (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  checked_at timestamptz,
  match_date text,
  kickoff_hkt timestamptz,
  league_zh text,
  home_en text,
  away_en text,
  state text,
  reason text,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.bet365_current (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  fetched_at timestamptz,
  match_date text,
  kickoff_hkt timestamptz,
  league text,
  home text,
  away text,
  bet365_home numeric,
  bet365_draw numeric,
  bet365_away numeric,
  bet365_fixture_id text,
  match_quality numeric,
  source text,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.form_predictions (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  fetched_at timestamptz,
  home text,
  away text,
  form_prob_home numeric,
  form_prob_draw numeric,
  form_prob_away numeric,
  form_xg_home numeric,
  form_xg_away numeric,
  home_games integer,
  away_games integer,
  home_venue_games integer,
  away_venue_games integer,
  quality text,
  model_source text,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.evaluation_summary (
  model text primary key,
  as_of_hkt timestamptz,
  settled_matches integer,
  avg_rps numeric,
  avg_brier numeric,
  avg_logloss numeric,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.odds_movement_current (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  captured_at timestamptz,
  kickoff_hkt timestamptz,
  home text,
  away text,
  movement_side text,
  now_odds numeric,
  odds_24h numeric,
  move_24h_pp numeric,
  odds_2h numeric,
  move_2h_pp numeric,
  odds_1h numeric,
  move_1h_pp numeric,
  vol_24h_pp numeric,
  signal text,
  model_side text,
  model_prob numeric,
  model_alignment text,
  match_confidence numeric,
  alert_score numeric,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.prediction_fallback_current (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  fetched_at timestamptz,
  kickoff_hkt timestamptz,
  hkjc_league text,
  home_en text,
  away_en text,
  source text,
  source_competition text,
  source_url text,
  recommendation text,
  market text,
  match_score numeric,
  status text,
  notes text,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.live_score_current (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  updated_at_source timestamptz,
  kickoff_hkt timestamptz,
  league text,
  home_en text,
  away_en text,
  live_score text,
  home_score integer,
  away_score integer,
  minute integer,
  match_status text,
  source text,
  source_match_id text,
  source_home text,
  source_away text,
  match_confidence numeric,
  source_updated_at timestamptz,
  home_corners integer,
  away_corners integer,
  total_corners integer,
  corner_line_ref text,
  corners_to_hi numeric,
  corner_progress text,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.human_factors_current (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  fetched_at timestamptz,
  home_injuries text,
  away_injuries text,
  home_lineup text,
  away_lineup text,
  home_rest_days numeric,
  away_rest_days numeric,
  home_travel text,
  away_travel text,
  motivation_stakes text,
  coach_rotation text,
  weather_pitch text,
  referee text,
  source text,
  quality text,
  notes text,
  raw_url text,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.forebet_supplement enable row level security;
alter table public.forebet_archive enable row level security;
alter table public.forebet_availability enable row level security;
alter table public.bet365_current enable row level security;
alter table public.form_predictions enable row level security;
alter table public.evaluation_summary enable row level security;
alter table public.odds_movement_current enable row level security;
alter table public.prediction_fallback_current enable row level security;
alter table public.live_score_current enable row level security;
alter table public.human_factors_current enable row level security;

create or replace view public.forebet_effective_v as
with latest_archive as (
  select distinct on (hkjc_event_id) *
  from public.forebet_archive
  order by hkjc_event_id, captured_at desc
)
select
  m.hkjc_event_id,
  coalesce(f.prob_home, s.prob_home, a.prob_home) as prob_home,
  coalesce(f.prob_draw, s.prob_draw, a.prob_draw) as prob_draw,
  coalesce(f.prob_away, s.prob_away, a.prob_away) as prob_away,
  coalesce(f.prediction_1x2, s.prediction_1x2, a.prediction_1x2) as prediction_1x2,
  coalesce(f.predicted_score, s.predicted_score, a.predicted_score) as predicted_score,
  coalesce(f.avg_goals, s.avg_goals, a.avg_goals) as avg_goals,
  coalesce(f.power_home, a.power_home) as power_home,
  coalesce(f.power_away, a.power_away) as power_away,
  coalesce(f.prediction_ou25, s.prediction_ou25, a.prediction_ou25) as prediction_ou25,
  coalesce(f.prob_over25, s.prob_over25, a.prob_over25) as prob_over25,
  coalesce(f.prob_under25, s.prob_under25, a.prob_under25) as prob_under25,
  coalesce(f.ou_predicted_score, s.ou_predicted_score, a.ou_predicted_score) as ou_predicted_score,
  coalesce(f.corner_prediction, s.corner_prediction, a.corner_prediction) as corner_prediction,
  coalesce(f.corner_prob_under95, s.corner_prob_under95, a.corner_prob_under95) as corner_prob_under95,
  coalesce(f.corner_prob_over95, s.corner_prob_over95, a.corner_prob_over95) as corner_prob_over95,
  coalesce(f.corner_predicted_score, s.corner_predicted_score, a.corner_predicted_score) as corner_predicted_score,
  coalesce(f.avg_corners, s.avg_corners, a.avg_corners) as avg_corners,
  case
    when f.hkjc_event_id is not null and f.prob_home is not null and f.prob_draw is not null and f.prob_away is not null then 'CURRENT'
    when s.hkjc_event_id is not null and s.prob_home is not null and s.prob_draw is not null and s.prob_away is not null then 'SUPPLEMENT'
    when a.hkjc_event_id is not null and a.prob_home is not null and a.prob_draw is not null and a.prob_away is not null then 'ARCHIVE'
    when s.status = 'NO_FOREBET_COVERAGE' then 'NO_FOREBET_COVERAGE'
    else coalesce(av.state, 'UNRESOLVED')
  end as forebet_status,
  greatest(
    coalesce(f.fetched_at, '-infinity'::timestamptz),
    coalesce(s.fetched_at, '-infinity'::timestamptz),
    coalesce(a.captured_at, '-infinity'::timestamptz),
    coalesce(av.checked_at, '-infinity'::timestamptz)
  ) as source_updated_at
from public.matches m
left join public.forebet_predictions f using (hkjc_event_id)
left join public.forebet_supplement s using (hkjc_event_id)
left join latest_archive a using (hkjc_event_id)
left join public.forebet_availability av using (hkjc_event_id);

create or replace view public.fast_tracker_live_v2 as
with base as (
  select
    m.*,
    h.had_home, h.had_draw, h.had_away,
    h.hil_line, h.hil_over, h.hil_under,
    h.chl_line, h.chl_over, h.chl_under,
    fb.prob_home as forebet_prob_home,
    fb.prob_draw as forebet_prob_draw,
    fb.prob_away as forebet_prob_away,
    fb.prediction_1x2 as forebet_pick,
    fb.predicted_score as forebet_score,
    fb.avg_goals as forebet_avg_goals,
    fb.power_home, fb.power_away,
    fb.prediction_ou25,
    fb.prob_under25,
    fb.prob_over25,
    fb.ou_predicted_score,
    fb.corner_prediction,
    fb.corner_prob_under95,
    fb.corner_prob_over95,
    fb.corner_predicted_score,
    fb.avg_corners,
    fb.forebet_status,
    fb.source_updated_at as forebet_source_updated_at,
    b.bet365_home, b.bet365_draw, b.bet365_away,
    md.dc_prob_home, md.dc_prob_draw, md.dc_prob_away,
    md.dc_xg_home, md.dc_xg_away, md.dc_prob_over25,
    md.pi_prob_home, md.pi_prob_draw, md.pi_prob_away,
    md.pi_diff,
    md.quality as shadow_status,
    fm.form_prob_home, fm.form_prob_draw, fm.form_prob_away,
    fm.form_xg_home, fm.form_xg_away, fm.quality as form_status,
    ap.recommendation as apwin_rec,
    ap.market as apwin_market,
    om.movement_side, om.now_odds as movement_now_odds,
    om.move_24h_pp, om.move_2h_pp, om.move_1h_pp,
    om.vol_24h_pp, om.signal as odds_signal,
    om.model_alignment as odds_model_alignment,
    om.alert_score as odds_alert_score,
    coalesce(ls.live_score, lsc.live_score) as live_score,
    coalesce(ls.match_minute, lsc.minute) as match_minute,
    coalesce(ls.match_status, lsc.match_status) as live_match_status,
    coalesce(ls.home_corners, lsc.home_corners) as home_corners,
    coalesce(ls.away_corners, lsc.away_corners) as away_corners,
    coalesce(ls.total_corners, lsc.total_corners) as total_corners,
    ls.team_stats,
    ls.events,
    ls.momentum
  from public.matches m
  left join public.hkjc_odds_current h using (hkjc_event_id)
  left join public.forebet_effective_v fb using (hkjc_event_id)
  left join public.bet365_current b using (hkjc_event_id)
  left join public.model_predictions md using (hkjc_event_id)
  left join public.form_predictions fm using (hkjc_event_id)
  left join public.prediction_fallback_current ap using (hkjc_event_id)
  left join public.odds_movement_current om using (hkjc_event_id)
  left join public.live_stats_current ls using (hkjc_event_id)
  left join public.live_score_current lsc using (hkjc_event_id)
  where m.selling is true
    and h.had_home is not null
    and h.had_draw is not null
    and h.had_away is not null
), calc as (
  select *,
    case when forebet_prob_home is null then null else had_home * forebet_prob_home / 100.0 - 1 end as edge_home,
    case when forebet_prob_draw is null then null else had_draw * forebet_prob_draw / 100.0 - 1 end as edge_draw,
    case when forebet_prob_away is null then null else had_away * forebet_prob_away / 100.0 - 1 end as edge_away,
    case
      when status ilike '%ENDED%' or now() >= kickoff_hkt + interval '150 minutes' then 'ENDED'
      when now() < kickoff_hkt then 'PRE'
      when in_play is true or status ilike '%INPLAY%' then 'LIVE'
      else 'CLOSED'
    end as market_phase,
    case
      when shadow_status = 'MODELED' then
        case
          when dc_prob_home >= dc_prob_draw and dc_prob_home >= dc_prob_away then 'H'
          when dc_prob_draw >= dc_prob_away then 'D'
          else 'A'
        end
      else null
    end as dc_hda,
    case
      when shadow_status = 'MODELED' then
        case
          when pi_prob_home >= pi_prob_draw and pi_prob_home >= pi_prob_away then 'H'
          when pi_prob_draw >= pi_prob_away then 'D'
          else 'A'
        end
      else null
    end as pi_hda,
    case forebet_pick when '1' then 'H' when 'X' then 'D' when '2' then 'A' else null end as forebet_hda
  from base
), best as (
  select *,
    greatest(edge_home, edge_draw, edge_away) as best_edge
  from calc
)
select *,
  case
    when best_edge is null then null
    when best_edge = edge_home then 'H · ' || home_en
    when best_edge = edge_draw then 'D'
    else 'A · ' || away_en
  end as best_bet,
  case
    when best_edge is null then null
    when best_edge = edge_home then had_home
    when best_edge = edge_draw then had_draw
    else had_away
  end as best_odds,
  case
    when forebet_prob_home is null or forebet_prob_draw is null or forebet_prob_away is null then 'NO FOREBET MODEL'
    when best_edge > 0 then 'POSITIVE EDGE'
    else 'NO EDGE'
  end as edge_status,
  case
    when shadow_status <> 'MODELED' then 'MODEL_UNAVAILABLE'
    when forebet_hda is null then 'NO_FOREBET'
    when forebet_hda = dc_hda then 'AGREE'
    else 'CONFLICT'
  end as forebet_dc,
  case
    when shadow_status <> 'MODELED' then 'LOCAL MODEL UNAVAILABLE'
    when dc_hda <> pi_hda then 'DC↔PI CONFLICT'
    when forebet_hda = dc_hda then 'FOREBET+DC+PI AGREE'
    else 'MODEL CONFLICT'
  end as consensus
from best;

create index if not exists odds_movement_alert_idx on public.odds_movement_current (alert_score desc);
