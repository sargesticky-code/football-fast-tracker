
create table if not exists public.competition_name_master (
  source text not null,
  source_competition text not null,
  source_key text not null,
  canonical_tournament text not null,
  status text not null default 'CANDIDATE',
  confidence numeric not null default 0,
  event_count integer not null default 0,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  evidence_sources jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (source, source_key, canonical_tournament)
);
alter table public.competition_name_master enable row level security;
create index if not exists competition_name_master_lookup_idx
  on public.competition_name_master(source,source_key,status);

create table if not exists public.team_name_context_master (
  source text not null,
  source_name text not null,
  source_key text not null,
  source_competition text not null default '',
  competition_key text not null default '',
  canonical_tournament text not null default '',
  team_key text not null references public.team_entities_v2(team_key) on delete cascade,
  hkjc_name_en text not null,
  hkjc_name_zh text,
  status text not null default 'CANDIDATE',
  confidence numeric not null default 0,
  event_count integer not null default 0,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  evidence_sources jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (source, source_key, competition_key, canonical_tournament, team_key)
);
alter table public.team_name_context_master enable row level security;
create index if not exists team_name_context_lookup_idx
  on public.team_name_context_master(source,competition_key,source_key,status);

create or replace view public.competition_name_lookup
with (security_invoker=true)
as
with verified as (
  select source,source_competition,source_key,canonical_tournament,confidence,event_count,last_seen_at,
         count(*) over(partition by source,source_key) target_count
  from public.competition_name_master
  where status='VERIFIED'
)
select source,source_competition,source_key,canonical_tournament,confidence,event_count,last_seen_at
from verified
where target_count=1;

create or replace view public.team_name_context_lookup
with (security_invoker=true)
as
with verified as (
  select source,source_name,source_key,source_competition,competition_key,canonical_tournament,
         team_key,hkjc_name_en,hkjc_name_zh,confidence,event_count,last_seen_at,
         count(*) over(partition by source,competition_key,source_key) target_count
  from public.team_name_context_master
  where status='VERIFIED'
)
select source,source_name,source_key,source_competition,competition_key,canonical_tournament,
       team_key,hkjc_name_en,hkjc_name_zh,confidence,event_count,last_seen_at
from verified
where target_count=1;

insert into public.team_alias_registry_v2(
  source,alias_key,team_key,alias,status,confidence,evidence_count,distinct_event_count,
  verification_method,first_seen_at,last_seen_at,updated_at
)
values
  ('FOREBET',public.ft_team_name_key('Inter Milano W'),'HKJC:intermilanwomen','Inter Milano W','VERIFIED',1.0,1,1,'MANUAL_SOURCE_FIXTURE',now(),now(),now()),
  ('FOREBET',public.ft_team_name_key('Hacken W'),'HKJC:hackenwomen','Hacken W','VERIFIED',1.0,1,1,'MANUAL_SOURCE_FIXTURE',now(),now(),now()),
  ('FOREBET',public.ft_team_name_key('Bayern Munich W'),'HKJC:bayernmunichwomen','Bayern Munich W','VERIFIED',1.0,1,1,'MANUAL_SOURCE_FIXTURE',now(),now(),now()),
  ('FOREBET',public.ft_team_name_key('Man City W'),'HKJC:manchestercitywomen','Man City W','VERIFIED',1.0,1,1,'MANUAL_SOURCE_FIXTURE',now(),now(),now())
on conflict(source,alias_key,team_key) do update set
  alias=excluded.alias,
  status='VERIFIED',
  confidence=greatest(public.team_alias_registry_v2.confidence,excluded.confidence),
  evidence_count=greatest(public.team_alias_registry_v2.evidence_count,excluded.evidence_count),
  distinct_event_count=greatest(public.team_alias_registry_v2.distinct_event_count,excluded.distinct_event_count),
  verification_method='MANUAL_SOURCE_FIXTURE',
  last_seen_at=now(),
  updated_at=now();

insert into public.team_alias_evidence_v2(
  source,alias,alias_key,team_key,hkjc_event_id,team_side,tournament,kickoff_hkt,
  evidence_type,confidence,observed_at,raw
)
select * from (
  values
    ('FOREBET','Inter Milano W',public.ft_team_name_key('Inter Milano W'),'HKJC:intermilanwomen','FB5605','H','UCLW',
      (select kickoff_hkt from public.matches where hkjc_event_id='FB5605'),
      'VERIFIED_SOURCE_FIXTURE',1.0,now(),
      jsonb_build_object('source_competition','CLW','source_url','https://www.forebet.com/en/football/matches/inter-milano-w-hacken-w-2552166')),
    ('FOREBET','Hacken W',public.ft_team_name_key('Hacken W'),'HKJC:hackenwomen','FB5605','A','UCLW',
      (select kickoff_hkt from public.matches where hkjc_event_id='FB5605'),
      'VERIFIED_SOURCE_FIXTURE',1.0,now(),
      jsonb_build_object('source_competition','CLW','source_url','https://www.forebet.com/en/football/matches/inter-milano-w-hacken-w-2552166')),
    ('FOREBET','Bayern Munich W',public.ft_team_name_key('Bayern Munich W'),'HKJC:bayernmunichwomen','FB5606','H','UCLW',
      (select kickoff_hkt from public.matches where hkjc_event_id='FB5606'),
      'VERIFIED_SOURCE_FIXTURE',1.0,now(),
      jsonb_build_object('source_competition','CLW','source_url','https://www.forebet.com/en/football/matches/bayern-munich-w-man-city-w-2552167')),
    ('FOREBET','Man City W',public.ft_team_name_key('Man City W'),'HKJC:manchestercitywomen','FB5606','A','UCLW',
      (select kickoff_hkt from public.matches where hkjc_event_id='FB5606'),
      'VERIFIED_SOURCE_FIXTURE',1.0,now(),
      jsonb_build_object('source_competition','CLW','source_url','https://www.forebet.com/en/football/matches/bayern-munich-w-man-city-w-2552167'))
) as v(source,alias,alias_key,team_key,hkjc_event_id,team_side,tournament,kickoff_hkt,evidence_type,confidence,observed_at,raw)
on conflict do nothing;

create or replace function public.ft_refresh_static_identity_context()
returns jsonb
language plpgsql
security definer
set search_path='pg_catalog','public','pg_temp'
as $$
begin
  insert into public.competition_name_master(
    source,source_competition,source_key,canonical_tournament,status,confidence,event_count,
    first_seen_at,last_seen_at,evidence_sources,updated_at
  )
  select
    'HKJC',
    max(m.tournament),
    public.ft_team_name_key(m.tournament),
    m.tournament,
    'VERIFIED',1.0,
    count(distinct m.hkjc_event_id)::int,
    min(coalesce(m.created_at,m.fetched_at,now())),
    max(coalesce(m.updated_at,m.fetched_at,now())),
    jsonb_build_array('HKJC_CANONICAL'),
    now()
  from public.matches m
  where nullif(trim(m.tournament),'') is not null
  group by public.ft_team_name_key(m.tournament),m.tournament
  on conflict(source,source_key,canonical_tournament) do update set
    source_competition=excluded.source_competition,
    status='VERIFIED',
    confidence=1.0,
    event_count=greatest(public.competition_name_master.event_count,excluded.event_count),
    first_seen_at=least(public.competition_name_master.first_seen_at,excluded.first_seen_at),
    last_seen_at=greatest(public.competition_name_master.last_seen_at,excluded.last_seen_at),
    updated_at=now();

  insert into public.competition_name_master(
    source,source_competition,source_key,canonical_tournament,status,confidence,event_count,
    first_seen_at,last_seen_at,evidence_sources,updated_at
  )
  select
    'FOREBET',
    max(fp.forebet_league_short),
    public.ft_team_name_key(fp.forebet_league_short),
    m.tournament,
    'VERIFIED',0.98,
    count(distinct fp.hkjc_event_id)::int,
    min(coalesce(fp.fetched_at,fp.updated_at,now())),
    max(coalesce(fp.fetched_at,fp.updated_at,now())),
    jsonb_build_array('FOREBET_EVENT_LINK'),
    now()
  from public.forebet_predictions fp
  join public.matches m using(hkjc_event_id)
  where nullif(trim(fp.forebet_league_short),'') is not null
    and nullif(trim(m.tournament),'') is not null
  group by public.ft_team_name_key(fp.forebet_league_short),m.tournament
  on conflict(source,source_key,canonical_tournament) do update set
    source_competition=excluded.source_competition,
    status='VERIFIED',
    confidence=greatest(public.competition_name_master.confidence,excluded.confidence),
    event_count=greatest(public.competition_name_master.event_count,excluded.event_count),
    first_seen_at=least(public.competition_name_master.first_seen_at,excluded.first_seen_at),
    last_seen_at=greatest(public.competition_name_master.last_seen_at,excluded.last_seen_at),
    evidence_sources=(
      select coalesce(jsonb_agg(distinct x),'[]'::jsonb)
      from jsonb_array_elements(
        coalesce(public.competition_name_master.evidence_sources,'[]'::jsonb)
        || excluded.evidence_sources
      ) x
    ),
    updated_at=now();

  insert into public.competition_name_master(
    source,source_competition,source_key,canonical_tournament,status,confidence,event_count,
    first_seen_at,last_seen_at,evidence_sources,updated_at
  )
  select
    e.source,
    max(e.raw->>'source_competition'),
    public.ft_team_name_key(e.raw->>'source_competition'),
    e.tournament,
    'VERIFIED',
    max(e.confidence),
    count(distinct e.hkjc_event_id)::int,
    min(e.observed_at),
    max(e.observed_at),
    jsonb_build_array('ALIAS_EVENT_CONTEXT'),
    now()
  from public.team_alias_evidence_v2 e
  where nullif(trim(e.raw->>'source_competition'),'') is not null
    and nullif(trim(e.tournament),'') is not null
  group by e.source,public.ft_team_name_key(e.raw->>'source_competition'),e.tournament
  on conflict(source,source_key,canonical_tournament) do update set
    source_competition=excluded.source_competition,
    status='VERIFIED',
    confidence=greatest(public.competition_name_master.confidence,excluded.confidence),
    event_count=greatest(public.competition_name_master.event_count,excluded.event_count),
    first_seen_at=least(public.competition_name_master.first_seen_at,excluded.first_seen_at),
    last_seen_at=greatest(public.competition_name_master.last_seen_at,excluded.last_seen_at),
    updated_at=now();

  insert into public.team_name_context_master(
    source,source_name,source_key,source_competition,competition_key,canonical_tournament,
    team_key,hkjc_name_en,hkjc_name_zh,status,confidence,event_count,first_seen_at,last_seen_at,
    evidence_sources,updated_at
  )
  select
    e.source,
    max(e.alias),
    e.alias_key,
    max(coalesce(e.raw->>'source_competition','')),
    coalesce(public.ft_team_name_key(e.raw->>'source_competition'),''),
    coalesce(e.tournament,''),
    e.team_key,
    te.hkjc_name_en,
    te.hkjc_name_zh,
    'VERIFIED',
    max(e.confidence),
    count(distinct e.hkjc_event_id)::int,
    min(e.observed_at),
    max(e.observed_at),
    jsonb_build_array('ALIAS_EVENT_CONTEXT'),
    now()
  from public.team_alias_evidence_v2 e
  join public.team_entities_v2 te using(team_key)
  join public.team_alias_registry_v2 r
    on r.source=e.source and r.alias_key=e.alias_key and r.team_key=e.team_key
  where r.status='VERIFIED'
  group by e.source,e.alias_key,coalesce(public.ft_team_name_key(e.raw->>'source_competition'),''),
           coalesce(e.tournament,''),e.team_key,te.hkjc_name_en,te.hkjc_name_zh
  on conflict(source,source_key,competition_key,canonical_tournament,team_key) do update set
    source_name=excluded.source_name,
    source_competition=excluded.source_competition,
    hkjc_name_en=excluded.hkjc_name_en,
    hkjc_name_zh=excluded.hkjc_name_zh,
    status='VERIFIED',
    confidence=greatest(public.team_name_context_master.confidence,excluded.confidence),
    event_count=greatest(public.team_name_context_master.event_count,excluded.event_count),
    first_seen_at=least(public.team_name_context_master.first_seen_at,excluded.first_seen_at),
    last_seen_at=greatest(public.team_name_context_master.last_seen_at,excluded.last_seen_at),
    updated_at=now();

  insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
  values(
    'STATIC_IDENTITY_MASTER','registry',
    (select count(*)::text from public.team_name_context_master where status='VERIFIED'),
    'OK',
    'Persistent source team + competition identity context; learned once and reused before runtime fuzzy discovery.',
    now(),
    jsonb_build_object(
      'competition_rows',(select count(*) from public.competition_name_master),
      'verified_competition_rows',(select count(*) from public.competition_name_master where status='VERIFIED'),
      'context_rows',(select count(*) from public.team_name_context_master),
      'verified_context_rows',(select count(*) from public.team_name_context_master where status='VERIFIED')
    )
  )
  on conflict(source,metric) do update set
    value_text=excluded.value_text,status=excluded.status,notes=excluded.notes,
    observed_at=excluded.observed_at,raw=excluded.raw;

  return jsonb_build_object(
    'competition_rows',(select count(*) from public.competition_name_master),
    'verified_competition_rows',(select count(*) from public.competition_name_master where status='VERIFIED'),
    'context_rows',(select count(*) from public.team_name_context_master),
    'verified_context_rows',(select count(*) from public.team_name_context_master where status='VERIFIED')
  );
end
$$;

revoke all on function public.ft_refresh_static_identity_context() from public;
revoke all on function public.ft_refresh_static_identity_context() from anon;
revoke all on function public.ft_refresh_static_identity_context() from authenticated;
grant execute on function public.ft_refresh_static_identity_context() to service_role;

create or replace function public.ft_alias_maintenance_v2()
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_refresh jsonb;
  v_promote jsonb;
  v_master jsonb;
  v_registry_merge jsonb;
  v_health jsonb;
  v_one_for_all jsonb;
  v_women jsonb;
  v_brazil jsonb;
  v_context jsonb;
begin
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  v_registry_merge := public.ft_merge_alias_registry_into_team_name_master();
  v_context := public.ft_refresh_static_identity_context();
  v_health := public.ft_record_team_name_master_health();
  v_one_for_all := public.ft_record_one_for_all_alias_health();
  v_women := public.ft_refresh_womens_intl_team_names();
  v_brazil := public.ft_refresh_brazilianfootball_team_names();

  update public.source_health
  set notes='Alias evidence registry v2 plus persistent static team/competition context. Phase 1 production identity is master-first; verified source/league mappings are learned once and reused.',
      observed_at=now()
  where source='TEAM_ALIAS_V2' and metric='registry';

  return jsonb_build_object(
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master,
    'registry_merge',v_registry_merge,
    'static_identity_context',v_context,
    'team_name_master_health',v_health,
    'one_for_all_health',v_one_for_all,
    'womens_intl_names',v_women,
    'brazilianfootball_names',v_brazil
  );
end
$$;
