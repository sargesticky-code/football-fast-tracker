create or replace view public.team_alias_actionable_queue_v2 as
select q.source,q.alias,q.alias_key,q.team_key,q.hkjc_name_en,q.hkjc_name_zh,q.status,q.confidence,q.evidence_count,q.distinct_event_count,q.verification_method,q.last_seen_at
from public.team_alias_candidate_queue_v2 q
where not exists (
  select 1 from public.team_name_master m
  where upper(m.source)=upper(q.source)
    and m.source_key=q.alias_key
    and m.status='VERIFIED'
)
and not exists (
  select 1 from public.phase1_identity_deferred_queue d
  where d.reactivated_at is null
    and upper(d.source)=upper(q.source)
    and regexp_replace(lower(d.source_name),'[^a-z0-9]+','','g')=q.alias_key
);
