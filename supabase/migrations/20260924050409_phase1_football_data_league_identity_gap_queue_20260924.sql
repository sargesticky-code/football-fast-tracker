create or replace view public.phase1_football_data_league_identity_gap_v as
with n as (
  select league_code, home_team as source_name, count(*)::int as event_count, min(first_seen_at) first_seen_at, max(updated_at) last_seen_at
  from public.football_data_matches group by 1,2
  union all
  select league_code, away_team, count(*)::int, min(first_seen_at), max(updated_at)
  from public.football_data_matches group by 1,2
), a as (
  select league_code, source_name, sum(event_count)::int event_count, min(first_seen_at) first_seen_at, max(last_seen_at) last_seen_at
  from n group by 1,2
), r as (
  select a.*, m.team_key, m.hkjc_name_en, m.status team_status,
         exists(select 1 from public.competition_name_master c where c.source='FOOTBALL_DATA' and c.status='VERIFIED' and (lower(c.source_competition)=lower(a.league_code) or lower(c.source_key)=regexp_replace(lower(a.league_code),'[^a-z0-9]+','','g'))) as exact_league_verified
  from a left join public.team_name_master m
    on m.source='FOOTBALL_DATA'
   and m.source_key=regexp_replace(lower(a.source_name),'[^a-z0-9]+','','g')
)
select league_code, source_name, team_key, hkjc_name_en, team_status, event_count, first_seen_at, last_seen_at,
       case when team_status='VERIFIED' and not exact_league_verified then 'NEEDS_VERIFIED_LEAGUE_ALIAS'
            when team_status is null then 'NEEDS_TEAM_IDENTITY'
            when team_status<>'VERIFIED' then 'TEAM_IDENTITY_NOT_VERIFIED'
            else 'READY' end as action
from r;
comment on view public.phase1_football_data_league_identity_gap_v is 'Phase 1 durable Football-Data source-name census by league. Separates verified team identity from missing league identity so provider coverage is not misclassified as source absence.';
