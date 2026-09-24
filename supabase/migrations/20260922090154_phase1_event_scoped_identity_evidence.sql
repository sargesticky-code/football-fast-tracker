create table if not exists public.team_name_event_context_master (
  source text not null,
  source_name text not null,
  source_competition text not null default '',
  hkjc_event_id text not null,
  side text not null check (side in ('HOME','AWAY')),
  team_key text not null,
  hkjc_name_en text,
  status text not null check (status in ('VERIFIED','CANDIDATE','AMBIGUOUS','BLOCKED')),
  confidence numeric not null default 0,
  evidence_sources jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (source,source_name,source_competition,hkjc_event_id,side,team_key)
);
alter table public.team_name_event_context_master enable row level security;
create index if not exists team_name_event_context_lookup_idx on public.team_name_event_context_master(source,source_name,source_competition,hkjc_event_id,side,status);
comment on table public.team_name_event_context_master is 'Phase 1 fail-closed event-scoped identity evidence for provider names that remain ambiguous even within one competition. Does not replace static team/competition master.';
