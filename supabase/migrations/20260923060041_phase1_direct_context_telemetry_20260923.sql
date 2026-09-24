create or replace view phase1_identity_direct_context_telemetry_v as
select c.source,
       count(*) filter (where c.status='VERIFIED') as verified_context_rows,
       count(distinct c.source_name) filter (where c.status='VERIFIED') as verified_source_names,
       count(distinct c.team_key) filter (where c.status='VERIFIED') as verified_team_keys,
       count(*) filter (where c.status<>'VERIFIED') as unresolved_context_rows
from team_name_context_master c
group by c.source;

create or replace view phase1_generic_alias_context_resolution_v as
select m.source,m.source_name,m.team_key,m.status as global_status,
       count(c.*) filter(where c.status='VERIFIED') as verified_context_hits,
       array_remove(array_agg(distinct c.source_competition) filter(where c.status='VERIFIED'),null) as verified_competitions,
       case when count(c.*) filter(where c.status='VERIFIED')>0 then 'DIRECT_CONTEXT_MASTER'
            else 'DISCOVERY_REQUIRED' end as runtime_path
from team_name_master m
left join team_name_context_master c
 on c.source=m.source and c.source_name=m.source_name and c.team_key=m.team_key
where m.status in ('CANDIDATE','AMBIGUOUS')
group by m.source,m.source_name,m.team_key,m.status;
