create table if not exists public.phase1_identity_safety_block (
  source text not null,
  source_key text not null,
  blocked_team_key text not null,
  block_reason text not null,
  cohort text,
  evidence_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (source, source_key, blocked_team_key)
);

insert into public.phase1_identity_safety_block(source,source_key,blocked_team_key,block_reason,cohort,evidence_note)
values ('OPTA','rheindorfaltachii','HKJC:rheindorfaltach','RESERVE_TO_SENIOR_BLOCK','RESERVE','Provider name explicitly identifies II/reserve side while candidate HKJC entity is senior Rheindorf Altach; never auto-promote without independent HKJC reserve canonical identity.')
on conflict (source,source_key,blocked_team_key) do update set block_reason=excluded.block_reason, cohort=excluded.cohort, evidence_note=excluded.evidence_note, updated_at=now();

create or replace view public.phase1_app_core_actionable_unresolved_v as
select u.*,
       case when b.source is not null then false else true end as actionable,
       coalesce(b.block_reason,u.identity_policy) as durable_policy
from public.phase1_app_core_unresolved_v u
left join public.phase1_identity_safety_block b
  on b.source=u.source and b.source_key=u.source_key and b.blocked_team_key=u.team_key
where u.identity_policy <> 'LEAGUE_CONTEXT_REQUIRED_SAFE_BLOCK'
   or b.source is not null;

create or replace view public.phase1_identity_safety_block_health_v as
select b.source,b.source_key,b.blocked_team_key,b.block_reason,b.cohort,
       m.status as current_master_status,
       case when m.status='VERIFIED' then 'VIOLATION' else 'SAFE' end as health
from public.phase1_identity_safety_block b
left join public.team_name_master m
  on m.source=b.source and m.source_key=b.source_key and m.team_key=b.blocked_team_key;
