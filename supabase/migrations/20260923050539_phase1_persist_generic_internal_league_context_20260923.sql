insert into public.competition_name_master (source,source_competition,source_key,canonical_tournament,status,confidence,event_count,first_seen_at,last_seen_at,evidence_sources,updated_at)
select v.source,v.comp,lower(regexp_replace(v.comp,'[^a-zA-Z0-9]+','','g')),v.comp,'VERIFIED',0.99,1,now(),now(),'["MULTISOURCE_HKJC_ANCHOR"]'::jsonb,now()
from (values ('ACC','USL'),('BCL','USL'),('FST','USL'),('ACC','UDC'),('BCL','UDC'),('FST','UDC')) v(source,comp)
where not exists (select 1 from public.competition_name_master c where c.source=v.source and c.source_competition=v.comp);

insert into public.team_name_context_master (source,source_name,source_key,source_competition,competition_key,canonical_tournament,team_key,hkjc_name_en,hkjc_name_zh,status,confidence,event_count,first_seen_at,last_seen_at,evidence_sources,updated_at)
select v.source,v.source_name,lower(regexp_replace(v.source_name,'[^a-zA-Z0-9]+','','g')),v.comp,lower(v.comp),v.comp,v.team_key,v.en,v.zh,'VERIFIED',v.conf,1,now(),now(),'["MULTISOURCE_HKJC_ANCHOR","LEAGUE_CONTEXT_PERSIST"]'::jsonb,now()
from (values
 ('ACC','Brooklyn','USL','HKJC:brooklynfc','Brooklyn FC','布魯克林FC',0.99::numeric),
 ('BCL','Brooklyn','USL','HKJC:brooklynfc','Brooklyn FC','布魯克林FC',0.99::numeric),
 ('FST','Brooklyn','USL','HKJC:brooklynfc','Brooklyn FC','布魯克林FC',0.99::numeric),
 ('ACC','Wanderers','UDC','HKJC:montevideowanderers','Montevideo Wanderers','蒙特維多流浪者',0.95::numeric),
 ('BCL','Wanderers','UDC','HKJC:montevideowanderers','Montevideo Wanderers','蒙特維多流浪者',0.95::numeric),
 ('FST','Wanderers','UDC','HKJC:montevideowanderers','Montevideo Wanderers','蒙特維多流浪者',0.95::numeric)
) v(source,source_name,comp,team_key,en,zh,conf)
where not exists (select 1 from public.team_name_context_master t where t.source=v.source and t.source_name=v.source_name and t.source_competition=v.comp and t.team_key=v.team_key);
