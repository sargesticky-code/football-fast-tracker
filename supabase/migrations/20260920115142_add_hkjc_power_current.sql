create table if not exists public.hkjc_power_current (
    hkjc_event_id text primary key references public.matches(hkjc_event_id) on delete cascade,
    fetched_at timestamptz,
    kickoff_hkt timestamptz,
    tournament text,
    home_en text,
    away_en text,
    home_rating numeric,
    away_rating numeric,
    home_opta_name text,
    away_opta_name text,
    home_match_confidence numeric,
    away_match_confidence numeric,
    home_rank integer,
    away_rank integer,
    coverage text,
    source text,
    power_updated timestamptz,
    raw jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
  );

  alter table public.hkjc_power_current enable row level security;

  create index if not exists idx_hkjc_power_current_kickoff
    on public.hkjc_power_current(kickoff_hkt);

  create index if not exists idx_hkjc_power_current_coverage
    on public.hkjc_power_current(coverage);
