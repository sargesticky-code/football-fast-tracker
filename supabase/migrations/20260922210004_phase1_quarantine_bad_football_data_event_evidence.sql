create table if not exists public.team_name_event_context_quarantine (
  source text not null,
  source_name text not null,
  source_competition text,
  hkjc_event_id text not null,
  side text,
  team_key text,
  hkjc_name_en text,
  original_status text,
  original_confidence numeric,
  evidence_sources jsonb,
  quarantine_reason text not null,
  quarantined_at timestamptz not null default now(),
  primary key (source, source_name, hkjc_event_id, team_key)
);

insert into public.team_name_event_context_quarantine
(source,source_name,source_competition,hkjc_event_id,side,team_key,hkjc_name_en,original_status,original_confidence,evidence_sources,quarantine_reason)
select source,source_name,source_competition,hkjc_event_id,side,team_key,hkjc_name_en,status,confidence,evidence_sources,
       'Provider source name contradicts Football-Data source row and HKJC event anchor; cross-event alias leakage' 
from public.team_name_event_context_master
where (source='FOOTBALL_DATA' and source_name='Dundee' and hkjc_event_id='FB5356' and team_key='HKJC:dundeeutd')
   or (source='FOOTBALL_DATA' and source_name='Man City' and hkjc_event_id='FB5339' and team_key='HKJC:manchesterutd')
on conflict do nothing;

delete from public.team_name_event_context_master
where (source='FOOTBALL_DATA' and source_name='Dundee' and hkjc_event_id='FB5356' and team_key='HKJC:dundeeutd')
   or (source='FOOTBALL_DATA' and source_name='Man City' and hkjc_event_id='FB5339' and team_key='HKJC:manchesterutd');

create index if not exists team_name_event_context_quarantine_lookup_idx
on public.team_name_event_context_quarantine(source, lower(source_name), source_competition, hkjc_event_id);
