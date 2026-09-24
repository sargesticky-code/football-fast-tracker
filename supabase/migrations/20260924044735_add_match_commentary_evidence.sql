
create table if not exists public.match_commentary_evidence (
  id bigint generated always as identity primary key,
  hkjc_event_id text not null references public.matches(hkjc_event_id) on delete cascade,
  source text not null,
  source_type text not null default 'EDITORIAL',
  source_url text,
  author text,
  published_at timestamptz,
  captured_at timestamptz not null default now(),
  language text,
  headline text,
  excerpt text,
  summary text,
  lean_market text,
  lean_selection text,
  confidence numeric,
  topics jsonb not null default '[]'::jsonb,
  provenance jsonb not null default '{}'::jsonb,
  content_fingerprint text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint match_commentary_excerpt_len check (excerpt is null or char_length(excerpt) <= 1000),
  constraint match_commentary_confidence_range check (confidence is null or (confidence >= 0 and confidence <= 1)),
  unique (hkjc_event_id, source, content_fingerprint)
);

create index if not exists match_commentary_event_published_idx
  on public.match_commentary_evidence (hkjc_event_id, published_at desc);

create index if not exists match_commentary_source_idx
  on public.match_commentary_evidence (source, captured_at desc);

alter table public.match_commentary_evidence enable row level security;
