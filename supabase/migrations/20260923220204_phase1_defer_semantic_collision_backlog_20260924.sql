insert into public.phase1_identity_deferred_queue (source,source_name,source_competition,reason,evidence_count,first_seen_at,last_seen_at,deferred_at,last_checked_at,reactivated_at,candidate_team_key)
values
('FOOTBALL_LIVE_API_SELF_HOSTED','Feyenoord','','NEEDS_LEAGUE_CONTEXT_MEN_WOMEN_COLLISION',2,now(),now(),now(),now(),null,null),
('FOOTBALL_LIVE_API_SELF_HOSTED','Rangers','','NEEDS_LEAGUE_CONTEXT_MEN_WOMEN_COLLISION',2,now(),now(),now(),now(),null,null),
('FOOTBALL_LIVE_API_SELF_HOSTED','Real Sociedad','','NEEDS_LEAGUE_CONTEXT_MEN_WOMEN_COLLISION',2,now(),now(),now(),now(),null,null),
('OPTA','Real Sociedad','','NEEDS_LEAGUE_CONTEXT_SENIOR_B_COLLISION',2,now(),now(),now(),now(),null,null),
('OPTA','Rheindorf Altach II','','RESERVE_CANONICAL_ENTITY_NOT_VERIFIED',1,now(),now(),now(),now(),null,'HKJC:rheindorfaltach')
on conflict (source,source_name,source_competition) do update set reason=excluded.reason,evidence_count=greatest(phase1_identity_deferred_queue.evidence_count,excluded.evidence_count),last_checked_at=now(),candidate_team_key=excluded.candidate_team_key;
