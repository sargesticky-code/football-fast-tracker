create table if not exists public.hkjc_live_odds_current (
    hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
    fetched_at timestamptz,
    match_id text,
    kickoff_hkt timestamptz,
    status text,
    tournament text,
    home_en text,
    away_en text,
    home_zh text,
    away_zh text,
    had_home numeric,
    had_draw numeric,
    had_away numeric,
    hil_line text,
    hil_over numeric,
    hil_under numeric,
    chl_line text,
    chl_over numeric,
    chl_under numeric,
    pool_status text,
    odds_updated_at timestamptz,
    raw jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
  );

  alter table public.hkjc_live_odds_current enable row level security;

  create index if not exists idx_hkjc_live_odds_current_fetched_at
    on public.hkjc_live_odds_current(fetched_at desc);

  create index if not exists idx_hkjc_live_odds_current_status
    on public.hkjc_live_odds_current(status, pool_status);
