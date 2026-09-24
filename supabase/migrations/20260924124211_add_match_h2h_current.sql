
create table if not exists public.match_h2h_current (
  hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
  fetched_at timestamptz not null,
  kickoff_hkt timestamptz,
  home_id text,
  away_id text,
  home text,
  away text,
  h2h_games smallint not null default 0,
  home_wins smallint not null default 0,
  draws smallint not null default 0,
  away_wins smallint not null default 0,
  home_goals integer not null default 0,
  away_goals integer not null default 0,
  avg_total_goals numeric,
  last5 text,
  meetings jsonb not null default '[]'::jsonb,
  source text not null,
  quality text not null,
  updated_at timestamptz not null default now(),
  constraint match_h2h_counts_nonnegative check (
    h2h_games >= 0 and home_wins >= 0 and draws >= 0 and away_wins >= 0
    and home_goals >= 0 and away_goals >= 0
  ),
  constraint match_h2h_outcome_total check (
    home_wins + draws + away_wins = h2h_games
  )
);

create index if not exists match_h2h_current_quality_idx
  on public.match_h2h_current (quality);

alter table public.match_h2h_current enable row level security;
revoke all on table public.match_h2h_current from anon, authenticated;

comment on table public.match_h2h_current is
  'Current verified HKJC head-to-head summary. Strict stable-team-ID matching only; zero prior meetings is a valid state, not a pipeline failure.';
