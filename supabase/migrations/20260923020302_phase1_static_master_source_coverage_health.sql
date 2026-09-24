create or replace view public.phase1_static_master_source_coverage_v as
with s as (
  select source,
         count(*) filter (where status='VERIFIED')::bigint as verified_aliases,
         count(*) filter (where status='CANDIDATE')::bigint as candidate_aliases,
         count(*) filter (where status='AMBIGUOUS')::bigint as ambiguous_aliases,
         count(distinct team_key) filter (where status='VERIFIED')::bigint as verified_team_keys,
         max(updated_at) as last_master_update_at
  from public.team_name_master
  group by source
), blockers as (
  select source,
         count(*) filter (where status in ('CANDIDATE','AMBIGUOUS'))::bigint as unsafe_fallback_blocks
  from public.team_name_master
  group by source
)
select s.source,s.verified_aliases,s.candidate_aliases,s.ambiguous_aliases,
       s.verified_team_keys,coalesce(b.unsafe_fallback_blocks,0) as unsafe_fallback_blocks,
       s.last_master_update_at
from s left join blockers b using(source);

create or replace view public.phase1_static_master_unresolved_v as
select source,source_name,source_key,team_key,hkjc_name_en,hkjc_name_zh,status,confidence,event_count,
       first_seen_at,last_seen_at,evidence_sources,updated_at,
       case when status='AMBIGUOUS' then 'COLLISION_REVIEW'
            when status='CANDIDATE' then 'EVIDENCE_PROMOTION_REVIEW'
            else 'OTHER_NON_VERIFIED' end as next_action
from public.team_name_master
where status <> 'VERIFIED';

comment on view public.phase1_static_master_source_coverage_v is 'Phase 1 static one-for-all identity inventory by provider; runtime fuzzy is not counted as coverage.';
comment on view public.phase1_static_master_unresolved_v is 'Persistent fail-closed queue of non-VERIFIED static aliases. VERIFIED rows are never downgraded here.';
