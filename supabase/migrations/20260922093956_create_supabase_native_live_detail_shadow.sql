
create table if not exists public.live_detail_shadow_current (
  hkjc_event_id text primary key,
  captured_at timestamptz not null,
  source text,
  source_match_id text,
  detail_status text,
  team_stats jsonb not null default '[]'::jsonb,
  events jsonb not null default '[]'::jsonb,
  momentum jsonb not null default '[]'::jsonb,
  home_corners numeric,
  away_corners numeric,
  total_corners numeric,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists live_detail_shadow_current_capture_idx
on public.live_detail_shadow_current(captured_at desc);

alter table public.live_detail_shadow_current enable row level security;
revoke all on public.live_detail_shadow_current from anon,authenticated;
grant select,insert,update,delete on public.live_detail_shadow_current to service_role;
