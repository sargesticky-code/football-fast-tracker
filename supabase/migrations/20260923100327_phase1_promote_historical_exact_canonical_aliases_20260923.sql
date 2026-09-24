insert into public.team_alias_registry_v2 (source,alias_key,team_key,alias,status,confidence,evidence_count,distinct_event_count,verification_method,first_seen_at,last_seen_at,updated_at)
select u.source,e.name_key,e.team_key,u.source_name,'VERIFIED',1.0,least(u.evidence_count,2147483647)::int,least(u.evidence_count,2147483647)::int,'HISTORICAL_SURFACE_EXACT_HKJC_CANONICAL',u.first_seen_at,u.last_seen_at,now()
from public.phase1_historical_surface_unseen_priority_v u
join public.team_entities_v2 e on lower(btrim(e.hkjc_name_en))=lower(btrim(u.source_name)) and e.status='ACTIVE'
where not exists (select 1 from public.team_alias_registry_v2 r where r.source=u.source and r.alias_key=e.name_key)
on conflict (source,alias_key,team_key) do nothing;
select public.ft_refresh_team_name_master();
