insert into public.team_alias_registry_v2(source,alias_key,team_key,alias,status,confidence,evidence_count,distinct_event_count,verification_method,first_seen_at,last_seen_at,updated_at)
select source,public.ft_team_name_key(source_name),candidate_team_key,source_name,'VERIFIED',1.0,evidence_count,evidence_count,'HISTORICAL_SURFACE_EXACT_NORMALIZED_HKJC_CANONICAL',first_seen_at,last_seen_at,now()
from public.phase1_historical_surface_unseen_classified_v
where source='FOOTBALL_DATA' and source_name='St Pauli' and source_competition='D2' and canonical_availability='HKJC_CANONICAL_AVAILABLE'
on conflict (source,alias_key,team_key) do update set alias=excluded.alias,status='VERIFIED',confidence=greatest(team_alias_registry_v2.confidence,excluded.confidence),evidence_count=greatest(team_alias_registry_v2.evidence_count,excluded.evidence_count),verification_method=excluded.verification_method,last_seen_at=greatest(team_alias_registry_v2.last_seen_at,excluded.last_seen_at),updated_at=now();
select public.ft_alias_maintenance_v2();
