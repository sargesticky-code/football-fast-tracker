insert into public.team_alias_registry_v2 (source,alias_key,team_key,alias,status,confidence,evidence_count,distinct_event_count,verification_method,first_seen_at,last_seen_at,updated_at)
values
('FOOTBALL_LIVE_API_SELF_HOSTED','evertonw','HKJC:evertonwomen','Everton (W)','VERIFIED',0.99,1,1,'STATIC_LEAGUE_AWARE_WOMEN_IDENTITY_UECW_ELCW',now(),now(),now()),
('FOOTBALL_LIVE_API_SELF_HOSTED','hammarbyif','HKJC:hammarbywomen','Hammarby IF','VERIFIED',0.99,1,1,'STATIC_LEAGUE_AWARE_WOMEN_IDENTITY_UECW_ELCW',now(),now(),now()),
('FOOTBALL_LIVE_API_SELF_HOSTED','heartofmidlothian','HKJC:heartswomen','Heart of Midlothian','VERIFIED',0.99,1,1,'STATIC_LEAGUE_AWARE_WOMEN_IDENTITY_UECW_ELCW',now(),now(),now()),
('FOOTBALL_LIVE_API_SELF_HOSTED','vålerenga','HKJC:valerengawomen','Vålerenga','VERIFIED',0.99,1,1,'STATIC_LEAGUE_AWARE_WOMEN_IDENTITY_UECW_ELCW',now(),now(),now())
on conflict (source,alias_key,team_key) do update set alias=excluded.alias,status='VERIFIED',confidence=greatest(team_alias_registry_v2.confidence,excluded.confidence),evidence_count=greatest(team_alias_registry_v2.evidence_count,excluded.evidence_count),distinct_event_count=greatest(team_alias_registry_v2.distinct_event_count,excluded.distinct_event_count),verification_method=excluded.verification_method,last_seen_at=greatest(team_alias_registry_v2.last_seen_at,excluded.last_seen_at),updated_at=now();
