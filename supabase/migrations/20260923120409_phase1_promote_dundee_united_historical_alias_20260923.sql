insert into public.team_alias_registry_v2 (source, alias_key, team_key, alias, status, confidence, evidence_count, distinct_event_count, verification_method, first_seen_at, last_seen_at, updated_at)
select 'FOOTBALL_DATA', regexp_replace(lower(u.source_name), '[^a-z0-9]+', '', 'g'), 'HKJC:dundeeutd', u.source_name, 'VERIFIED', 1.0, u.evidence_count, u.evidence_count, 'HISTORICAL_SURFACE_LEAGUE_AWARE_CANONICAL_VARIANT', u.first_seen_at, u.last_seen_at, now()
from public.phase1_historical_surface_unseen_priority_v u
where u.source='FOOTBALL_DATA' and u.source_competition='SC0' and u.source_name='Dundee United'
on conflict (source, alias_key, team_key) do update set alias=excluded.alias,status='VERIFIED',confidence=1.0,evidence_count=greatest(team_alias_registry_v2.evidence_count,excluded.evidence_count),distinct_event_count=greatest(team_alias_registry_v2.distinct_event_count,excluded.distinct_event_count),verification_method=excluded.verification_method,last_seen_at=greatest(team_alias_registry_v2.last_seen_at,excluded.last_seen_at),updated_at=now();
select public.ft_refresh_team_name_master();
