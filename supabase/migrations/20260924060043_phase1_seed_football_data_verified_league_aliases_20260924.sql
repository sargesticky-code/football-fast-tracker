with m(league_code,canonical_tournament) as (values ('E0','EPL'),('E1','ED1'),('E2','ED2'),('E3','ED3'),('EC','ENL'),('SC0','SPL'),('D1','BD1'),('D2','BD2'),('F1','FFL'),('F2','FF2'),('SP1','SFL'),('SP2','SF2'),('I1','ISA'),('N1','NTL'),('P1','PFL'),('B1','BFL'),('G1','GSL'),('T1','TL1')), g as (select league_code,sum(event_count)::int appearances from public.phase1_football_data_league_identity_gap_v group by league_code)
insert into public.competition_name_master (source,source_competition,source_key,canonical_tournament,status,confidence,event_count,first_seen_at,last_seen_at,evidence_sources,updated_at)
select 'FOOTBALL_DATA',m.league_code,lower(m.league_code),m.canonical_tournament,'VERIFIED',1.0,coalesce(g.appearances,0),now(),now(),jsonb_build_object('method','STATIC_FOOTBALL_DATA_CODE_TO_HKJC_COMPETITION','league_code',m.league_code,'historical_appearances',coalesce(g.appearances,0)),now()
from m left join g using(league_code)
where exists (select 1 from public.competition_name_master h where h.source='HKJC' and h.status='VERIFIED' and h.canonical_tournament=m.canonical_tournament)
and not exists (select 1 from public.competition_name_master x where x.source='FOOTBALL_DATA' and x.source_key=lower(m.league_code));

update public.competition_name_master x set status='VERIFIED',confidence=greatest(x.confidence,1.0),updated_at=now()
from (values ('E0','EPL'),('E1','ED1'),('E2','ED2'),('E3','ED3'),('EC','ENL'),('SC0','SPL'),('D1','BD1'),('D2','BD2'),('F1','FFL'),('F2','FF2'),('SP1','SFL'),('SP2','SF2'),('I1','ISA'),('N1','NTL'),('P1','PFL'),('B1','BFL'),('G1','GSL'),('T1','TL1')) m(league_code,canonical_tournament)
where x.source='FOOTBALL_DATA' and x.source_key=lower(m.league_code) and x.canonical_tournament=m.canonical_tournament;
