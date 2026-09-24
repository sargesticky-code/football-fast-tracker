-- Promote only semantically specific internal aliases with a single HKJC target.
-- Generic names (Brooklyn, Wanderers) and reserve/senior collisions remain fail-closed.
update team_alias_registry_v2 r
set status='VERIFIED',
    confidence=greatest(r.confidence,0.95),
    verification_method='STATIC_UNIQUE_CANONICAL_SYNONYM',
    updated_at=now()
where (r.source,r.alias_key,r.team_key) in (
 ('BCL','southkorea','HKJC:korearepublic'),
 ('FST','southkorea','HKJC:korearepublic'),
 ('PRE','southkorea','HKJC:korearepublic'),
 ('STA','minerosdezacatecas','HKJC:mineroszacatecas')
)
and r.status='CANDIDATE'
and not exists (
  select 1 from team_alias_registry_v2 x
  where x.source=r.source and x.alias_key=r.alias_key and x.team_key<>r.team_key
    and x.status in ('VERIFIED','CANDIDATE','AMBIGUOUS')
);

-- Persist immediately in the runtime static master; the registry promotion makes it survive rebuilds.
update team_name_master m
set status='VERIFIED', confidence=greatest(m.confidence,0.95), updated_at=now()
where (m.source,m.source_key,m.team_key) in (
 ('BCL','southkorea','HKJC:korearepublic'),
 ('FST','southkorea','HKJC:korearepublic'),
 ('PRE','southkorea','HKJC:korearepublic'),
 ('STA','minerosdezacatecas','HKJC:mineroszacatecas')
)
and m.status='CANDIDATE';

create or replace view phase1_static_master_unresolved_action_v as
select u.*,
 case
  when u.source='OPTA' and u.source_key='realsociedad' then 'LEAGUE_CONTEXT_REQUIRED_SAFE_BLOCK'
  when u.source='OPTA' and u.source_key='rheindorfaltachii' then 'RESERVE_TO_SENIOR_BLOCK'
  when u.source_key in ('wanderers','brooklyn') then 'GENERIC_NAME_NEEDS_LEAGUE_OR_REPEAT_EVIDENCE'
  else u.next_action
 end as identity_policy
from phase1_static_master_unresolved_v u;
