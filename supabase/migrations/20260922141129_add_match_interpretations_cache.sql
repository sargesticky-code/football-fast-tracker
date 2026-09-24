
create table if not exists public.match_interpretations (
  hkjc_event_id text not null,
  language text not null default 'zh-HK',
  style text not null default 'professional',
  analysis_hash text,
  framework text not null default 'vercel-ai',
  model text,
  payload jsonb not null default '{}'::jsonb,
  source_generated_at timestamptz,
  generated_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (hkjc_event_id, language, style)
);

alter table public.match_interpretations enable row level security;

revoke all on table public.match_interpretations from anon, authenticated;

create index if not exists match_interpretations_updated_idx
  on public.match_interpretations (updated_at desc);

comment on table public.match_interpretations is
  'Cached grounded narrative interpretations. AI may explain deterministic evidence but must not override betting selection, odds, edge or action.';
