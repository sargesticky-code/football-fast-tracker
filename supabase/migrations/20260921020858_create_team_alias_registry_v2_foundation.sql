create or replace function public.ft_team_name_key(p_name text)
returns text
language sql
immutable
as $$
  select nullif(
    regexp_replace(lower(trim(coalesce(p_name,''))), '[^[:alnum:]]+', '', 'g'),
    ''
  )
$$;

create table public.team_entities_v2 (
  team_key text primary key,
  name_key text not null unique,
  hkjc_name_en text not null,
  hkjc_name_zh text,
  first_seen_at timestamptz,
  last_seen_at timestamptz,
  status text not null default 'ACTIVE',
  updated_at timestamptz not null default now()
);

create table public.team_alias_evidence_v2 (
  evidence_id bigint generated always as identity primary key,
  source text not null,
  alias text not null,
  alias_key text not null,
  team_key text not null references public.team_entities_v2(team_key),
  hkjc_event_id text,
  team_side text check (team_side in ('H','A')),
  tournament text,
  kickoff_hkt timestamptz,
  evidence_type text not null,
  confidence numeric,
  observed_at timestamptz not null default now(),
  raw jsonb not null default '{}'::jsonb
);

create unique index team_alias_evidence_v2_event_uq
on public.team_alias_evidence_v2 (
  source, alias_key, team_key, coalesce(hkjc_event_id,''), coalesce(team_side,'')
);

create index team_alias_evidence_v2_lookup_idx
on public.team_alias_evidence_v2(source,alias_key);

create index team_alias_evidence_v2_team_idx
on public.team_alias_evidence_v2(team_key);

create table public.team_alias_registry_v2 (
  source text not null,
  alias_key text not null,
  team_key text not null references public.team_entities_v2(team_key),
  alias text not null,
  status text not null,
  confidence numeric,
  evidence_count integer not null default 0,
  distinct_event_count integer not null default 0,
  verification_method text,
  first_seen_at timestamptz,
  last_seen_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key(source,alias_key,team_key)
);

create index team_alias_registry_v2_status_idx
on public.team_alias_registry_v2(source,status);

create table public.team_alias_gap_queue_v2 (
  source text not null,
  team_key text not null references public.team_entities_v2(team_key),
  hkjc_name_en text not null,
  hkjc_name_zh text,
  last_event_id text,
  tournament text,
  reason text,
  occurrence_count integer not null default 1,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key(source,team_key)
);

alter table public.team_entities_v2 enable row level security;
alter table public.team_alias_evidence_v2 enable row level security;
alter table public.team_alias_registry_v2 enable row level security;
alter table public.team_alias_gap_queue_v2 enable row level security;

create view public.team_alias_resolved_v2 as
with verified as (
  select
    r.*,
    count(*) filter (where r.status='VERIFIED') over(partition by r.source,r.alias_key) as verified_targets
  from public.team_alias_registry_v2 r
)
select
  v.source,
  v.alias,
  v.alias_key,
  v.team_key,
  t.hkjc_name_en,
  t.hkjc_name_zh,
  v.confidence,
  v.evidence_count,
  v.distinct_event_count,
  v.verification_method,
  v.last_seen_at
from verified v
join public.team_entities_v2 t using(team_key)
where v.status='VERIFIED'
  and v.verified_targets=1;

create view public.team_alias_candidate_queue_v2 as
select
  r.source,
  r.alias,
  r.alias_key,
  r.team_key,
  t.hkjc_name_en,
  t.hkjc_name_zh,
  r.status,
  r.confidence,
  r.evidence_count,
  r.distinct_event_count,
  r.verification_method,
  r.last_seen_at
from public.team_alias_registry_v2 r
join public.team_entities_v2 t using(team_key)
where r.status in ('CANDIDATE','AMBIGUOUS');
