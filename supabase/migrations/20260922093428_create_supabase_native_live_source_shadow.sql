
create table if not exists public.live_source_shadow_current (
  hkjc_event_id text primary key,
  captured_at timestamptz not null,
  target_state text not null,
  kickoff_hkt timestamptz,
  league text,
  home_en text,
  away_en text,
  source text,
  source_match_id text,
  match_confidence numeric,
  provider_home text,
  provider_away text,
  provider_kickoff timestamptz,
  provider_live boolean,
  home_score integer,
  away_score integer,
  minute integer,
  match_status text,
  detail_status text,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists live_source_shadow_current_capture_idx
on public.live_source_shadow_current(captured_at desc);

create index if not exists live_source_shadow_current_source_idx
on public.live_source_shadow_current(source,source_match_id);

alter table public.live_source_shadow_current enable row level security;
revoke all on public.live_source_shadow_current from anon,authenticated;
grant select,insert,update,delete on public.live_source_shadow_current to service_role;
