create or replace view public.phase1_static_source_name_census_v as
with phase1_sources(source) as (
  values ('FOREBET'),('FOOTBALL_DATA'),('OPTA'),('FORM'),('APWIN'),('FRB'),('ACC'),('BCL'),('FST'),('PRE'),('STA')
), global_rows as (
  select m.source, m.source_name, m.source_key, null::text as source_competition,
         null::text as competition_key, m.team_key, m.hkjc_name_en, m.status,
         m.event_count, m.first_seen_at, m.last_seen_at, 'GLOBAL_MASTER'::text as registry_layer
  from public.team_name_master m join phase1_sources p on p.source=m.source
), context_rows as (
  select c.source, c.source_name, c.source_key, c.source_competition,
         c.competition_key, c.team_key, c.hkjc_name_en, c.status,
         c.event_count, c.first_seen_at, c.last_seen_at, 'LEAGUE_CONTEXT_MASTER'::text as registry_layer
  from public.team_name_context_master c join phase1_sources p on p.source=c.source
)
select * from global_rows
union all
select * from context_rows;

create or replace view public.phase1_static_source_census_health_v as
select source,
       count(*) as registry_rows,
       count(*) filter (where registry_layer='GLOBAL_MASTER') as global_rows,
       count(*) filter (where registry_layer='LEAGUE_CONTEXT_MASTER') as context_rows,
       count(*) filter (where status='VERIFIED') as verified_rows,
       count(*) filter (where status='CANDIDATE') as candidate_rows,
       count(*) filter (where status='AMBIGUOUS') as ambiguous_rows,
       count(distinct source_key) as distinct_source_names,
       count(distinct team_key) filter (where status='VERIFIED') as verified_team_keys,
       count(distinct competition_key) filter (where registry_layer='LEAGUE_CONTEXT_MASTER' and status='VERIFIED') as verified_competitions,
       max(last_seen_at) as latest_evidence_at
from public.phase1_static_source_name_census_v
group by source;
