insert into public.team_name_master (source,source_name,source_key,team_key,hkjc_name_en,hkjc_name_zh,status,confidence,event_count,first_seen_at,last_seen_at,evidence_sources,updated_at)
select 'FOOTBALL_DATA', x.source_name, x.source_key, x.team_key, x.hkjc_name_en, x.hkjc_name_zh, 'VERIFIED', 0.99, x.event_count, now(), now(), jsonb_build_object('method','CROSS_SOURCE_EXACT_NAME_UNANIMOUS','league_code',x.league_code,'verified_cross_source_team_keys',1), now()
from (
 select g.league_code,g.source_name,g.event_count,count(distinct m.team_key) keys,min(m.team_key) team_key,min(m.hkjc_name_en) hkjc_name_en,min(m.hkjc_name_zh) hkjc_name_zh,min(m.source_key) source_key
 from public.phase1_football_data_league_identity_gap_v g
 join public.team_name_master m on m.source_name=g.source_name and m.status='VERIFIED' and m.source<>'FOOTBALL_DATA'
 where g.action='NEEDS_TEAM_IDENTITY'
 group by g.league_code,g.source_name,g.event_count
) x
where x.keys=1 and not exists (select 1 from public.team_name_master z where z.source='FOOTBALL_DATA' and z.source_key=x.source_key);
