insert into team_alias_registry_v2(source,alias_key,team_key,alias,status,confidence,evidence_count,distinct_event_count,verification_method,first_seen_at,last_seen_at,updated_at)
select 'FOOTBALL_DATA', regexp_replace(lower(trim(x.alias)),'[^a-z0-9]+','','g'), e.team_key, x.alias, 'VERIFIED', 1.0, u.evidence_count, u.evidence_count, 'HISTORICAL_SURFACE_LEAGUE_AWARE_ABBREVIATION', u.first_seen_at,u.last_seen_at,now()
from (values ('Ath Madrid','Atletico Madrid','SP1'),('West Brom','West Bromwich','E1')) x(alias,canonical,comp)
join team_entities_v2 e on e.hkjc_name_en=x.canonical and e.status='ACTIVE'
join phase1_historical_surface_unseen_priority_v u on u.source='FOOTBALL_DATA' and u.source_name=x.alias and u.source_competition=x.comp
where not exists (select 1 from team_alias_registry_v2 r where r.source='FOOTBALL_DATA' and r.alias_key=regexp_replace(lower(trim(x.alias)),'[^a-z0-9]+','','g'));
select ft_refresh_team_name_master();
