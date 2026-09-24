create table if not exists public.hkjc_upcoming_current (
    hkjc_event_id text primary key,
    fetched_at timestamptz not null,
    match_id text,
    kickoff_hkt timestamptz,
    status text,
    tournament text,
    home_en text,
    away_en text,
    home_zh text,
    away_zh text,
    live_eligible boolean,
    selling boolean,
    pool_status text,
    had_home numeric,
    had_draw numeric,
    had_away numeric,
    hil_line text,
    hil_over numeric,
    hil_under numeric,
    chl_line text,
    chl_over numeric,
    chl_under numeric,
    odds_updated_at timestamptz,
    raw jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
  );

  alter table public.hkjc_upcoming_current enable row level security;

  create index if not exists idx_hkjc_upcoming_current_kickoff
    on public.hkjc_upcoming_current(kickoff_hkt);

  create index if not exists idx_hkjc_upcoming_current_fetched
    on public.hkjc_upcoming_current(fetched_at desc);
