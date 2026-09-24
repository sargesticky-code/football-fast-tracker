create table if not exists public.phase3_live_identity_map (
  hkjc_event_id text not null,
  source text not null,
  source_match_id text not null,
  confidence numeric not null check (confidence >= 0 and confidence <= 1),
  evidence_count integer not null default 1 check (evidence_count > 0),
  first_verified_at timestamptz not null,
  last_verified_at timestamptz not null,
  mapping_state text not null default 'VERIFIED' check (mapping_state in ('VERIFIED','REJECTED','REVIEW')),
  evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (hkjc_event_id, source),
  unique (source, source_match_id)
);
create index if not exists phase3_live_identity_map_state_idx on public.phase3_live_identity_map(mapping_state, last_verified_at desc);

with agg as (
  select hkjc_event_id, source, source_match_id,
         count(*)::int as observations,
         min(match_confidence)::numeric as min_conf,
         min(captured_at_hkt) as first_seen,
         max(captured_at_hkt) as last_seen
  from public.live_stats_history
  where source_match_id is not null and match_confidence >= 0.85
  group by hkjc_event_id, source, source_match_id
), variants as (
  select hkjc_event_id, source, count(*)::int as id_variants
  from agg group by hkjc_event_id, source
), stable as (
  select a.* from agg a join variants v using(hkjc_event_id,source)
  where a.observations >= 3 and v.id_variants = 1
)
insert into public.phase3_live_identity_map
(hkjc_event_id,source,source_match_id,confidence,evidence_count,first_verified_at,last_verified_at,mapping_state,evidence)
select hkjc_event_id,source,source_match_id,min_conf,observations,first_seen,last_seen,'VERIFIED',
       jsonb_build_object('method','repeated_live_observation','minimum_confidence',min_conf,'observations',observations,'id_variants',1)
from stable
on conflict (hkjc_event_id,source) do update set
 source_match_id=excluded.source_match_id,
 confidence=excluded.confidence,
 evidence_count=excluded.evidence_count,
 first_verified_at=least(phase3_live_identity_map.first_verified_at,excluded.first_verified_at),
 last_verified_at=greatest(phase3_live_identity_map.last_verified_at,excluded.last_verified_at),
 mapping_state='VERIFIED', evidence=excluded.evidence, updated_at=now();

create or replace view public.phase3_live_identity_coverage_v as
select a.hkjc_event_id,a.match_id,a.home_en,a.away_en,a.status,a.pool_status,a.authority_fetched_at,a.authority_age_seconds,
       m.source,m.source_match_id,m.confidence,m.evidence_count,m.last_verified_at,m.mapping_state,
       case when m.mapping_state='VERIFIED' and m.confidence>=0.85 then 'MAPPED_VERIFIED' else 'UNMAPPED' end as identity_state
from public.phase3_hkjc_live_authority_v a
left join public.phase3_live_identity_map m on m.hkjc_event_id=a.hkjc_event_id and m.mapping_state='VERIFIED'
where a.eligible;
