create table if not exists public.phase1_identity_deferred_queue (
 source text not null, source_name text not null, source_competition text not null default '', reason text not null,
 evidence_count bigint not null default 0, first_seen_at timestamptz, last_seen_at timestamptz,
 deferred_at timestamptz not null default now(), last_checked_at timestamptz not null default now(), reactivated_at timestamptz,
 candidate_team_key text, primary key(source,source_name,source_competition));
insert into public.phase1_identity_deferred_queue(source,source_name,source_competition,reason,evidence_count,first_seen_at,last_seen_at,last_checked_at,candidate_team_key)
select source,source_name,coalesce(source_competition,''),'NO_HKJC_CANONICAL_ENTITY',evidence_count,first_seen_at,last_seen_at,now(),candidate_team_key
from public.phase1_historical_surface_unseen_classified_v where canonical_availability='NO_HKJC_CANONICAL_ENTITY'
on conflict(source,source_name,source_competition) do update set evidence_count=excluded.evidence_count,last_seen_at=excluded.last_seen_at,last_checked_at=now();
create or replace view public.phase1_identity_deferred_reactivation_v as
select d.*,e.team_key newly_available_team_key,e.hkjc_name_en newly_available_hkjc_name
from public.phase1_identity_deferred_queue d join public.team_entities_v2 e on e.name_key=regexp_replace(lower(d.source_name),'[^a-z0-9]+','','g')
where d.reason='NO_HKJC_CANONICAL_ENTITY' and d.reactivated_at is null and coalesce(e.status,'ACTIVE')='ACTIVE';
create or replace view public.phase1_identity_deferred_health_v as
select reason,count(*) deferred_rows,sum(evidence_count) evidence_count,count(*) filter(where reactivated_at is null) waiting_rows,count(*) filter(where reactivated_at is not null) reactivated_rows from public.phase1_identity_deferred_queue group by reason;
