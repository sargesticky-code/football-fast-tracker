create table if not exists public.phase3_live_identity_candidate (
  hkjc_event_id text not null,
  source text not null,
  source_match_id text not null,
  candidate_confidence numeric not null check (candidate_confidence >= 0 and candidate_confidence <= 1),
  evidence_count integer not null default 1 check (evidence_count >= 1),
  candidate_state text not null default 'CANDIDATE' check (candidate_state in ('CANDIDATE','REJECTED','PROMOTABLE')),
  evidence jsonb not null default '{}'::jsonb,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  primary key (hkjc_event_id, source, source_match_id)
);
create unique index if not exists phase3_identity_candidate_source_match_unique on public.phase3_live_identity_candidate(source,source_match_id) where candidate_state <> 'REJECTED';
create or replace view public.phase3_live_identity_coverage_health_v as
select
  count(*)::int as eligible_rows,
  count(*) filter (where c.identity_state='MAPPED_VERIFIED')::int as verified_rows,
  count(*) filter (where c.identity_state='UNMAPPED')::int as unmapped_rows,
  case when count(*)=0 then 1.0 else round((count(*) filter (where c.identity_state='MAPPED_VERIFIED'))::numeric/count(*),3) end as verified_coverage,
  min(c.confidence) filter (where c.identity_state='MAPPED_VERIFIED') as min_verified_confidence,
  min(c.evidence_count) filter (where c.identity_state='MAPPED_VERIFIED') as min_verified_evidence,
  now() as checked_at
from public.phase3_live_identity_coverage_v c;
