-- Fast Tracker Supabase core schema
-- PostgreSQL-first: all core data remains portable outside Supabase.

create extension if not exists pgcrypto;

create table if not exists public.matches (
  hkjc_event_id text primary key,
  hkjc_match_id text,
  kickoff_hkt timestamptz,
  status text,
  tournament text,
  home_en text,
  away_en text,
  home_zh text,
  away_zh text,
  pools text,
  pool_status text,
  in_play boolean,
  selling boolean,
  fetched_at timestamptz,
  source_updated_at timestamptz,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists matches_kickoff_idx on public.matches (kickoff_hkt);
create index if not exists matches_status_idx on public.matches (status);
create index if not exists matches_selling_idx on public.matches (selling, kickoff_hkt);

create table if not exists public.hkjc_odds_current (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  had_home numeric,
  had_draw numeric,
  had_away numeric,
  hil_line text,
  hil_over numeric,
  hil_under numeric,
  chl_line text,
  chl_over numeric,
  chl_under numeric,
  fetched_at timestamptz,
  odds_updated_at timestamptz,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.forebet_predictions (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  fetched_at timestamptz,
  forebet_match_date text,
  forebet_kickoff_text text,
  forebet_league_short text,
  forebet_home_team text,
  forebet_away_team text,
  prob_home numeric,
  prob_draw numeric,
  prob_away numeric,
  prediction_1x2 text,
  predicted_score text,
  avg_goals numeric,
  odds_home numeric,
  odds_draw numeric,
  odds_away numeric,
  prediction_ou25 text,
  prob_over25 numeric,
  prob_under25 numeric,
  odds_over25 numeric,
  odds_under25 numeric,
  forebet_detail_url text,
  match_score numeric,
  ou_predicted_score text,
  corner_prediction text,
  corner_prob_under95 numeric,
  corner_prob_over95 numeric,
  corner_predicted_score text,
  avg_corners numeric,
  power_home numeric,
  power_away numeric,
  power_home_name text,
  power_away_name text,
  power_source text,
  power_updated timestamptz,
  power_home_match boolean,
  power_away_match boolean,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.model_predictions (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  fetched_at timestamptz,
  home text,
  away text,
  model_league text,
  model_home_name text,
  model_away_name text,
  dc_prob_home numeric,
  dc_prob_draw numeric,
  dc_prob_away numeric,
  dc_xg_home numeric,
  dc_xg_away numeric,
  dc_prob_over25 numeric,
  pi_prob_home numeric,
  pi_prob_draw numeric,
  pi_prob_away numeric,
  pi_home_rating numeric,
  pi_away_rating numeric,
  pi_diff numeric,
  training_matches integer,
  team_match_quality numeric,
  quality text,
  model_source text,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.team_aliases (
  source text not null default 'FOREBET',
  alias text not null,
  canonical_hkjc_name text not null,
  confidence numeric,
  first_seen_hkt timestamptz,
  last_seen_hkt timestamptz,
  match_count integer,
  status text,
  alias_source text,
  updated_at timestamptz not null default now(),
  primary key (source, alias)
);

create index if not exists team_aliases_canonical_idx on public.team_aliases (canonical_hkjc_name);

create table if not exists public.live_stats_current (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  captured_at_hkt timestamptz,
  api_updated_at timestamptz,
  kickoff_hkt timestamptz,
  league text,
  home_en text,
  away_en text,
  live_score text,
  match_minute integer,
  match_status text,
  source text,
  source_match_id text,
  match_confidence numeric,
  detail_status text,
  home_corners integer,
  away_corners integer,
  total_corners integer,
  corner_line_ref text,
  corner_progress text,
  team_stats jsonb not null default '[]'::jsonb,
  events jsonb not null default '[]'::jsonb,
  momentum jsonb not null default '[]'::jsonb,
  full_capture boolean,
  raw_full_capture_key text,
  raw_full_chunk_count integer,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.live_stats_history (
  id bigint generated always as identity primary key,
  hkjc_event_id text references public.matches(hkjc_event_id) on delete cascade,
  captured_at_hkt timestamptz not null,
  api_updated_at timestamptz,
  kickoff_hkt timestamptz,
  league text,
  home_en text,
  away_en text,
  live_score text,
  match_minute integer,
  match_status text,
  source text,
  source_match_id text,
  match_confidence numeric,
  detail_status text,
  home_corners integer,
  away_corners integer,
  total_corners integer,
  corner_line_ref text,
  corner_progress text,
  team_stats jsonb not null default '[]'::jsonb,
  events jsonb not null default '[]'::jsonb,
  momentum jsonb not null default '[]'::jsonb,
  full_capture boolean,
  raw_full_capture_key text,
  raw_full_chunk_count integer,
  raw jsonb not null default '{}'::jsonb,
  unique (hkjc_event_id, captured_at_hkt)
);

create index if not exists live_stats_history_event_time_idx
  on public.live_stats_history (hkjc_event_id, captured_at_hkt desc);

create table if not exists public.odds_snapshots (
  id bigint generated always as identity primary key,
  hkjc_event_id text references public.matches(hkjc_event_id) on delete cascade,
  captured_at timestamptz not null,
  source text not null,
  market text not null,
  line text,
  home_price numeric,
  draw_price numeric,
  away_price numeric,
  over_price numeric,
  under_price numeric,
  raw jsonb not null default '{}'::jsonb,
  unique (hkjc_event_id, captured_at, source, market, line)
);

create index if not exists odds_snapshots_event_time_idx
  on public.odds_snapshots (hkjc_event_id, captured_at desc);

create table if not exists public.source_health (
  source text not null,
  metric text not null,
  value_text text,
  status text,
  notes text,
  observed_at timestamptz not null default now(),
  raw jsonb not null default '{}'::jsonb,
  primary key (source, metric)
);

create table if not exists public.ingest_runs (
  id bigint generated always as identity primary key,
  source text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'RUNNING',
  rows_seen integer not null default 0,
  rows_written integer not null default 0,
  error_text text,
  details jsonb not null default '{}'::jsonb
);

create or replace view public.fast_tracker_live_v as
select
  m.hkjc_event_id,
  m.kickoff_hkt,
  m.status,
  m.tournament,
  m.home_en,
  m.away_en,
  m.home_zh,
  m.away_zh,
  m.in_play,
  m.selling,
  h.had_home,
  h.had_draw,
  h.had_away,
  h.hil_line,
  h.hil_over,
  h.hil_under,
  h.chl_line,
  h.chl_over,
  h.chl_under,
  f.prob_home as forebet_prob_home,
  f.prob_draw as forebet_prob_draw,
  f.prob_away as forebet_prob_away,
  f.prediction_1x2 as forebet_pick,
  f.predicted_score as forebet_score,
  f.avg_goals as forebet_avg_goals,
  f.prediction_ou25 as forebet_ou25,
  f.prob_over25 as forebet_prob_over25,
  f.prob_under25 as forebet_prob_under25,
  f.corner_prediction as forebet_corner_pick,
  f.corner_prob_under95,
  f.corner_prob_over95,
  f.corner_predicted_score,
  f.avg_corners,
  f.power_home,
  f.power_away,
  md.dc_prob_home,
  md.dc_prob_draw,
  md.dc_prob_away,
  md.dc_xg_home,
  md.dc_xg_away,
  md.dc_prob_over25,
  md.pi_prob_home,
  md.pi_prob_draw,
  md.pi_prob_away,
  md.quality as model_quality,
  ls.live_score,
  ls.match_minute,
  ls.match_status,
  ls.home_corners,
  ls.away_corners,
  ls.total_corners,
  ls.team_stats,
  ls.events,
  ls.momentum,
  greatest(
    coalesce(m.fetched_at, '-infinity'::timestamptz),
    coalesce(h.fetched_at, '-infinity'::timestamptz),
    coalesce(f.fetched_at, '-infinity'::timestamptz),
    coalesce(md.fetched_at, '-infinity'::timestamptz),
    coalesce(ls.captured_at_hkt, '-infinity'::timestamptz)
  ) as data_updated_at
from public.matches m
left join public.hkjc_odds_current h using (hkjc_event_id)
left join public.forebet_predictions f using (hkjc_event_id)
left join public.model_predictions md using (hkjc_event_id)
left join public.live_stats_current ls using (hkjc_event_id);

alter table public.matches enable row level security;
alter table public.hkjc_odds_current enable row level security;
alter table public.forebet_predictions enable row level security;
alter table public.model_predictions enable row level security;
alter table public.team_aliases enable row level security;
alter table public.live_stats_current enable row level security;
alter table public.live_stats_history enable row level security;
alter table public.odds_snapshots enable row level security;
alter table public.source_health enable row level security;
alter table public.ingest_runs enable row level security;

-- No anon/authenticated policies by default.
-- Server-side jobs use the Supabase service-role key and bypass RLS.
