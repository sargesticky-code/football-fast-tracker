insert into public.team_alias_registry_v2 (source,alias_key,team_key,alias,status,confidence,evidence_count,distinct_event_count,verification_method,first_seen_at,last_seen_at,updated_at)
values
('SPORTSCORE','aselfensaitama','HKJC:elfensaitamawomen','AS Elfen Saitama','VERIFIED',0.99,1,1,'STATIC_LEAGUE_AWARE_WOMEN_IDENTITY',now(),now(),now()),
('SPORTSCORE','cerezoosakasakai','HKJC:cerezoosakawomen','Cerezo Osaka Sakai','VERIFIED',0.99,1,1,'STATIC_LEAGUE_AWARE_WOMEN_IDENTITY',now(),now(),now()),
('SPORTSCORE','nojimastellakanagawasagamihara','HKJC:nojimastellasagamiharawomen','Nojima Stella Kanagawa Sagamihara','VERIFIED',0.99,1,1,'STATIC_LEAGUE_AWARE_WOMEN_IDENTITY',now(),now(),now()),
('SPORTSCORE','sanfreccehiroshimaregina','HKJC:sanfreccehiroshimawomen','Sanfrecce Hiroshima Regina','VERIFIED',0.99,1,1,'STATIC_LEAGUE_AWARE_WOMEN_IDENTITY',now(),now(),now())
on conflict (source,alias_key,team_key) do update set
 alias=excluded.alias,
 status=case when team_alias_registry_v2.status='VERIFIED' then team_alias_registry_v2.status else excluded.status end,
 confidence=greatest(team_alias_registry_v2.confidence,excluded.confidence),
 evidence_count=greatest(team_alias_registry_v2.evidence_count,excluded.evidence_count),
 distinct_event_count=greatest(team_alias_registry_v2.distinct_event_count,excluded.distinct_event_count),
 verification_method=case when team_alias_registry_v2.status='VERIFIED' then team_alias_registry_v2.verification_method else excluded.verification_method end,
 last_seen_at=greatest(team_alias_registry_v2.last_seen_at,excluded.last_seen_at),
 updated_at=now();
