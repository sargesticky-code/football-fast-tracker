create or replace view public.phase1_historical_surface_unseen_census_v as
with raw_names as (
  select 'FOREBET'::text source, forebet_home_team source_name, forebet_league_short source_competition, count(*) evidence_count, min(fetched_at) first_seen_at, max(fetched_at) last_seen_at from public.forebet_predictions where nullif(btrim(forebet_home_team),'') is not null group by 1,2,3
  union all
  select 'FOREBET', forebet_away_team, forebet_league_short, count(*), min(fetched_at), max(fetched_at) from public.forebet_predictions where nullif(btrim(forebet_away_team),'') is not null group by 1,2,3
  union all
  select 'FOOTBALL_DATA', home_team, league_code, count(*), min(first_seen_at), max(updated_at) from public.football_data_matches where nullif(btrim(home_team),'') is not null group by 1,2,3
  union all
  select 'FOOTBALL_DATA', away_team, league_code, count(*), min(first_seen_at), max(updated_at) from public.football_data_matches where nullif(btrim(away_team),'') is not null group by 1,2,3
  union all
  select 'FORM', home, null::text, count(*), min(fetched_at), max(updated_at) from public.form_predictions where nullif(btrim(home),'') is not null group by 1,2,3
  union all
  select 'FORM', away, null::text, count(*), min(fetched_at), max(updated_at) from public.form_predictions where nullif(btrim(away),'') is not null group by 1,2,3
), rolled as (
 select source, source_name, source_competition, sum(evidence_count)::bigint evidence_count, min(first_seen_at) first_seen_at, max(last_seen_at) last_seen_at
 from raw_names group by 1,2,3
)
select r.*,
 case when gm.source_name is not null then 'DIRECT_GLOBAL_MASTER'
      when cm.source_name is not null then 'DIRECT_CONTEXT_MASTER'
      else 'UNSEEN_STATIC_MASTER' end identity_state
from rolled r
left join lateral (select m.source_name from public.team_name_master m where m.source=r.source and lower(btrim(m.source_name))=lower(btrim(r.source_name)) limit 1) gm on true
left join lateral (select c.source_name from public.team_name_context_master c where c.source=r.source and lower(btrim(c.source_name))=lower(btrim(r.source_name)) and (r.source_competition is null or lower(btrim(c.source_competition))=lower(btrim(r.source_competition))) limit 1) cm on true;

create or replace view public.phase1_historical_surface_unseen_priority_v as
select * from public.phase1_historical_surface_unseen_census_v
where identity_state='UNSEEN_STATIC_MASTER'
order by evidence_count desc, source, source_name;
