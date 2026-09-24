create or replace view public.phase1_historical_surface_unseen_classified_v as
with u as (
  select * from public.phase1_historical_surface_unseen_priority_v
), c as (
  select team_key,hkjc_name_en,hkjc_name_zh,status,
         public.ft_team_name_key(hkjc_name_en) en_key,
         public.ft_team_name_key(hkjc_name_zh) zh_key
  from public.team_entities_v2
), m as (
  select u.*, c.team_key candidate_team_key,c.hkjc_name_en candidate_hkjc_name_en,c.status canonical_status,
         count(c.team_key) over(partition by u.source,u.source_name,u.source_competition) canonical_match_count
  from u left join c on public.ft_team_name_key(u.source_name) in (c.en_key,c.zh_key)
)
select source,source_name,source_competition,evidence_count,first_seen_at,last_seen_at,identity_state,
       candidate_team_key,candidate_hkjc_name_en,canonical_status,
       case when candidate_team_key is null then 'NO_HKJC_CANONICAL_ENTITY'
            when canonical_match_count=1 and canonical_status='ACTIVE' then 'HKJC_CANONICAL_AVAILABLE'
            else 'HKJC_CANONICAL_COLLISION_OR_INACTIVE' end canonical_availability
from m;

create or replace view public.phase1_historical_surface_unseen_classification_health_v as
select source,canonical_availability,count(*) row_count,sum(evidence_count)::bigint evidence_count
from public.phase1_historical_surface_unseen_classified_v
group by source,canonical_availability;
