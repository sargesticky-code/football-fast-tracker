create table if not exists public.phase2_players (
    player_key text primary key,
    canonical_name text not null,
    team_key text,
    team_name text,
    position text,
    nationality text,
    date_of_birth date,
    sofascore_player_id bigint,
    transfermarkt_player_id text,
    source_ids jsonb not null default '{}'::jsonb,
    profile jsonb not null default '{}'::jsonb,
    source_updated_at timestamptz,
    updated_at timestamptz not null default now()
  );

  create table if not exists public.phase2_managers (
    manager_key text primary key,
    canonical_name text not null,
    team_key text,
    team_name text,
    nationality text,
    sofascore_manager_id bigint,
    transfermarkt_manager_id text,
    appointed_at date,
    contract_until date,
    profile jsonb not null default '{}'::jsonb,
    source_updated_at timestamptz,
    updated_at timestamptz not null default now()
  );

  create table if not exists public.phase2_player_status_evidence (
    id bigint generated always as identity primary key,
    hkjc_event_id text,
    team_side text check (team_side in ('H','A')),
    team_key text,
    player_key text,
    status_type text not null,
    status_value text,
    confirmed boolean not null default false,
    confidence numeric,
    valid_from timestamptz,
    valid_until timestamptz,
    source_name text not null,
    source_url text,
    source_published_at timestamptz,
    fetched_at timestamptz not null default now(),
    raw jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
  );

  create table if not exists public.phase2_match_lineup_evidence (
    id bigint generated always as identity primary key,
    hkjc_event_id text not null,
    team_side text not null check (team_side in ('H','A')),
    team_key text,
    player_key text,
    player_name text,
    role text,
    starter boolean,
    formation_slot text,
    shirt_number integer,
    confirmed boolean not null default false,
    confidence numeric,
    source_name text not null,
    source_url text,
    source_updated_at timestamptz,
    fetched_at timestamptz not null default now(),
    raw jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
  );

  create table if not exists public.phase2_manager_evidence (
    id bigint generated always as identity primary key,
    hkjc_event_id text,
    team_side text check (team_side in ('H','A')),
    team_key text,
    manager_key text,
    evidence_type text not null,
    evidence_value text,
    confirmed boolean not null default false,
    confidence numeric,
    source_name text not null,
    source_url text,
    source_published_at timestamptz,
    fetched_at timestamptz not null default now(),
    raw jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
  );

  create index if not exists idx_phase2_status_event on public.phase2_player_status_evidence(hkjc_event_id);
  create index if not exists idx_phase2_status_player on public.phase2_player_status_evidence(player_key);
  create index if not exists idx_phase2_lineup_event on public.phase2_match_lineup_evidence(hkjc_event_id);
  create index if not exists idx_phase2_manager_event on public.phase2_manager_evidence(hkjc_event_id);

  alter table public.phase2_players enable row level security;
  alter table public.phase2_managers enable row level security;
  alter table public.phase2_player_status_evidence enable row level security;
  alter table public.phase2_match_lineup_evidence enable row level security;
  alter table public.phase2_manager_evidence enable row level security;
