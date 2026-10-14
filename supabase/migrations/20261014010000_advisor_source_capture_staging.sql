-- Source-only evidence staging. This migration MUST NOT be applied automatically
-- by the advisor capture workflow. Canonical identities remain unresolved.
create table if not exists public.advisor_source_captures (
    provider text not null check (provider in ('BETCLAN', 'SPORTYTRADER')),
    provider_event_id text not null,
    evidence_hash text not null check (length(evidence_hash) = 64),
    captured_at timestamptz not null,
    source_url text not null,
    source_home text not null,
    source_away text not null,
    source_competition text,
    source_kickoff_text text,
    source_timezone_verified boolean not null default false,
    prediction_1x2 jsonb not null default '{}'::jsonb,
    goals_25 jsonb not null default '{}'::jsonb,
    btts jsonb not null default '{}'::jsonb,
    correct_score jsonb not null default '{}'::jsonb,
    source_tip text,
    canonical_match_id text,
    identity_status text not null default 'UNRESOLVED'
        check (identity_status in ('UNRESOLVED', 'VERIFIED', 'QUARANTINED')),
    identity_evidence jsonb,
    created_at timestamptz not null default now(),
    primary key (provider, provider_event_id, evidence_hash),
    constraint advisor_verified_requires_event_id
        check (identity_status <> 'VERIFIED' or
               (canonical_match_id is not null and identity_evidence is not null))
);
create index if not exists advisor_source_unresolved_idx
    on public.advisor_source_captures (provider, captured_at desc)
    where identity_status = 'UNRESOLVED';
create index if not exists advisor_source_match_idx
    on public.advisor_source_captures (canonical_match_id, captured_at desc)
    where identity_status = 'VERIFIED';
alter table public.advisor_source_captures enable row level security;
revoke all on public.advisor_source_captures from anon, authenticated;
grant select, insert, update on public.advisor_source_captures to service_role;
comment on table public.advisor_source_captures is
    'Immutable-ish source forecast revisions, de-duplicated by source/event/evidence hash. No automatic canonical promotion. Backend only.';
