
create table if not exists public.phase15_source_registry (
  source_key text primary key,
  source_kind text not null default 'OBSERVED',
  source_url text,
  trust_status text not null default 'EXPERIMENTAL'
    check (trust_status in ('TRUSTED','EXPERIMENTAL','QUARANTINED','DISABLED')),
  active boolean not null default true,
  discovery_enabled boolean not null default false,
  trust_score numeric not null default 0 check (trust_score >= 0 and trust_score <= 1),
  consecutive_success integer not null default 0,
  consecutive_failure integer not null default 0,
  total_records bigint not null default 0,
  last_probe_at timestamptz,
  last_success_at timestamptz,
  last_failure_at timestamptz,
  schema_fingerprint text,
  notes text,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  raw jsonb not null default '{}'::jsonb
);

create table if not exists public.phase15_source_shadow_current (
  source_key text not null,
  external_event_id text not null,
  fetched_at timestamptz not null default now(),
  kickoff_utc timestamptz,
  league_name text,
  league_external_id text,
  home_name text,
  away_name text,
  home_external_id text,
  away_external_id text,
  match_status text,
  matched_hkjc_event_id text,
  match_confidence numeric,
  identity_status text not null default 'UNMATCHED',
  detail_available boolean not null default false,
  lineup_available boolean not null default false,
  xg_available boolean not null default false,
  stats_available boolean not null default false,
  detail_fetched_at timestamptz,
  schema_fingerprint text,
  first_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  raw jsonb not null default '{}'::jsonb,
  detail_raw jsonb,
  primary key (source_key, external_event_id)
);

create index if not exists phase15_shadow_hkjc_idx
  on public.phase15_source_shadow_current (matched_hkjc_event_id);
create index if not exists phase15_shadow_kickoff_idx
  on public.phase15_source_shadow_current (kickoff_utc);

create table if not exists public.phase15_data_opportunity_queue (
  opportunity_id bigint generated always as identity primary key,
  hkjc_event_id text not null,
  gap_type text not null,
  target_field text not null,
  source_hint text not null,
  priority integer not null default 50 check (priority between 1 and 100),
  status text not null default 'OPEN'
    check (status in ('OPEN','RETRY','RESOLVED','DEFERRED','QUARANTINED')),
  reason text,
  attempt_count integer not null default 0,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  next_attempt_at timestamptz not null default now(),
  resolved_at timestamptz,
  last_result text,
  context jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  unique (hkjc_event_id, gap_type, source_hint)
);

create index if not exists phase15_opportunity_open_idx
  on public.phase15_data_opportunity_queue (status, priority desc, next_attempt_at);

create table if not exists public.phase15_discovery_runs (
  run_id bigint generated always as identity primary key,
  runner text not null default 'PHASE15',
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'RUNNING'
    check (status in ('RUNNING','OK','WARN','FAILED')),
  sources_seen integer not null default 0,
  opportunities_opened integer not null default 0,
  opportunities_resolved integer not null default 0,
  evidence_learned integer not null default 0,
  notes text,
  raw jsonb not null default '{}'::jsonb
);

alter table public.phase15_source_registry enable row level security;
alter table public.phase15_source_shadow_current enable row level security;
alter table public.phase15_data_opportunity_queue enable row level security;
alter table public.phase15_discovery_runs enable row level security;

revoke all on public.phase15_source_registry from anon, authenticated;
revoke all on public.phase15_source_shadow_current from anon, authenticated;
revoke all on public.phase15_data_opportunity_queue from anon, authenticated;
revoke all on public.phase15_discovery_runs from anon, authenticated;

insert into public.phase15_source_registry
  (source_key, source_kind, source_url, trust_status, active, discovery_enabled, trust_score, notes)
values
  ('HKJC','AUTHORITY','https://football.hkjc.com/','TRUSTED',true,false,1.00,'Canonical fixture and market authority'),
  ('FOREBET','PRODUCTION','https://www.forebet.com/','TRUSTED',true,false,0.95,'Existing production prediction source'),
  ('FOOTBALL_DATA','PRODUCTION','https://www.football-data.co.uk/','TRUSTED',true,false,0.90,'Existing historical source; private-use restrictions retained'),
  ('API_FOOTBALL','PRODUCTION','https://www.api-football.com/','TRUSTED',true,false,0.90,'Existing Phase 2 enrichment API'),
  ('FOTMOB','EXPERIMENTAL','https://www.fotmob.com/api/data/matches','EXPERIMENTAL',true,true,0.25,'Phase 1.5 shadow-only source; no production influence until promoted'),
  ('FOOTBALL_DATA_ORG','CANDIDATE','https://api.football-data.org/v4/','EXPERIMENTAL',true,false,0.10,'Candidate API; token required before active discovery')
on conflict (source_key) do update
set source_kind=excluded.source_kind,
    source_url=coalesce(excluded.source_url, public.phase15_source_registry.source_url),
    notes=excluded.notes,
    updated_at=now();

create or replace function private.ft_phase15_learn_exact_shadow()
returns integer
language plpgsql
security definer
set search_path = 'public','private'
as $$
declare
  v_before bigint;
  v_after bigint;
begin
  select count(*) into v_before from public.team_alias_evidence_v2 where source='FOTMOB';

  insert into public.team_alias_evidence_v2
    (source, alias, alias_key, team_key, hkjc_event_id, team_side, tournament,
     kickoff_hkt, evidence_type, confidence, observed_at, raw)
  select
    'FOTMOB',
    x.alias,
    public.ft_team_name_key(x.alias),
    x.team_key,
    s.matched_hkjc_event_id,
    x.side,
    u.tournament,
    u.kickoff_hkt,
    'PHASE15_EXACT_PAIR',
    0.99,
    s.fetched_at,
    jsonb_build_object('source_event_id',s.external_event_id,'identity_status',s.identity_status)
  from public.phase15_source_shadow_current s
  join public.hkjc_upcoming_current u
    on u.hkjc_event_id=s.matched_hkjc_event_id
  cross join lateral (
    select s.home_name alias, 'HOME'::text side, mh.team_key
    from public.team_name_master mh
    where mh.source='HKJC_EN'
      and mh.status='VERIFIED'
      and mh.source_key=public.ft_team_name_key(u.home_en)
    union all
    select s.away_name alias, 'AWAY'::text side, ma.team_key
    from public.team_name_master ma
    where ma.source='HKJC_EN'
      and ma.status='VERIFIED'
      and ma.source_key=public.ft_team_name_key(u.away_en)
  ) x
  where s.source_key='FOTMOB'
    and s.identity_status='EXACT_PAIR'
    and s.match_confidence >= 0.99
    and public.ft_team_name_key(s.home_name)=public.ft_team_name_key(u.home_en)
    and public.ft_team_name_key(s.away_name)=public.ft_team_name_key(u.away_en)
  on conflict do nothing;

  select count(*) into v_after from public.team_alias_evidence_v2 where source='FOTMOB';
  return (v_after-v_before)::integer;
end
$$;

create or replace function private.ft_phase15_discovery_maintenance()
returns jsonb
language plpgsql
security definer
set search_path = 'public','private'
as $$
declare
  v_run_id bigint;
  v_learned integer := 0;
  v_opened integer := 0;
  v_resolved integer := 0;
  v_rows integer := 0;
  v_sources integer := 0;
begin
  insert into public.phase15_discovery_runs(runner) values ('PHASE15_DB')
  returning run_id into v_run_id;

  insert into public.phase15_source_registry
    (source_key, source_kind, trust_status, active, discovery_enabled, trust_score,
     first_seen_at, last_seen_at, updated_at, notes)
  select
    m.source,
    'OBSERVED',
    'TRUSTED',
    true,
    false,
    0.80,
    min(m.first_seen_at),
    max(m.last_seen_at),
    now(),
    'Observed by One-for-All team identity master'
  from public.team_name_master m
  where m.source is not null
  group by m.source
  on conflict (source_key) do update
    set last_seen_at=greatest(public.phase15_source_registry.last_seen_at,excluded.last_seen_at),
        updated_at=now();

  select count(*) into v_sources from public.phase15_source_registry where active;

  v_learned := private.ft_phase15_learn_exact_shadow();

  insert into public.phase15_data_opportunity_queue
    (hkjc_event_id,gap_type,target_field,source_hint,priority,status,reason,
     first_seen_at,last_seen_at,next_attempt_at,context,updated_at)
  select
    u.hkjc_event_id,'PREDICTION_MISSING','forebet_prediction','FOREBET',
    case when u.kickoff_hkt <= now()+interval '24 hours' then 85 else 65 end,
    'OPEN','HKJC fixture has no Forebet prediction row',
    now(),now(),now(),
    jsonb_build_object('kickoff_hkt',u.kickoff_hkt,'tournament',u.tournament,'home',u.home_en,'away',u.away_en),
    now()
  from public.hkjc_upcoming_current u
  left join public.forebet_predictions f on f.hkjc_event_id=u.hkjc_event_id
  where u.kickoff_hkt between now()-interval '3 hours' and now()+interval '48 hours'
    and f.hkjc_event_id is null
  on conflict (hkjc_event_id,gap_type,source_hint) do update
    set status='OPEN', last_seen_at=now(), next_attempt_at=least(public.phase15_data_opportunity_queue.next_attempt_at,now()),
        priority=greatest(public.phase15_data_opportunity_queue.priority,excluded.priority),
        context=excluded.context, updated_at=now();
  get diagnostics v_rows = row_count;
  v_opened := v_opened + v_rows;

  insert into public.phase15_data_opportunity_queue
    (hkjc_event_id,gap_type,target_field,source_hint,priority,status,reason,
     first_seen_at,last_seen_at,next_attempt_at,context,updated_at)
  select
    u.hkjc_event_id,'MODEL_MISSING','internal_model','INTERNAL_MODEL',
    case when u.kickoff_hkt <= now()+interval '24 hours' then 75 else 55 end,
    'OPEN','HKJC fixture has no internal model row',
    now(),now(),now(),
    jsonb_build_object('kickoff_hkt',u.kickoff_hkt,'tournament',u.tournament,'home',u.home_en,'away',u.away_en),
    now()
  from public.hkjc_upcoming_current u
  left join public.model_predictions m on m.hkjc_event_id=u.hkjc_event_id
  where u.kickoff_hkt between now()-interval '3 hours' and now()+interval '48 hours'
    and m.hkjc_event_id is null
  on conflict (hkjc_event_id,gap_type,source_hint) do update
    set status='OPEN', last_seen_at=now(), priority=greatest(public.phase15_data_opportunity_queue.priority,excluded.priority),
        context=excluded.context, updated_at=now();
  get diagnostics v_rows = row_count;
  v_opened := v_opened + v_rows;

  insert into public.phase15_data_opportunity_queue
    (hkjc_event_id,gap_type,target_field,source_hint,priority,status,reason,
     first_seen_at,last_seen_at,next_attempt_at,context,updated_at)
  select
    u.hkjc_event_id,'HUMAN_FACTOR_MISSING','lineup_injury_referee','API_FOOTBALL',
    case when u.kickoff_hkt <= now()+interval '12 hours' then 90 else 70 end,
    'OPEN','Lineup/injury/referee enrichment is missing or empty',
    now(),now(),now(),
    jsonb_build_object('kickoff_hkt',u.kickoff_hkt,'tournament',u.tournament,'home',u.home_en,'away',u.away_en),
    now()
  from public.hkjc_upcoming_current u
  left join public.human_factors_current h on h.hkjc_event_id=u.hkjc_event_id
  where u.kickoff_hkt between now()-interval '3 hours' and now()+interval '48 hours'
    and (
      h.hkjc_event_id is null or
      (
        nullif(trim(coalesce(h.home_lineup,'')),'') is null and
        nullif(trim(coalesce(h.away_lineup,'')),'') is null and
        nullif(trim(coalesce(h.home_injuries,'')),'') is null and
        nullif(trim(coalesce(h.away_injuries,'')),'') is null and
        nullif(trim(coalesce(h.referee,'')),'') is null
      )
    )
  on conflict (hkjc_event_id,gap_type,source_hint) do update
    set status='OPEN', last_seen_at=now(), priority=greatest(public.phase15_data_opportunity_queue.priority,excluded.priority),
        context=excluded.context, updated_at=now();
  get diagnostics v_rows = row_count;
  v_opened := v_opened + v_rows;

  insert into public.phase15_data_opportunity_queue
    (hkjc_event_id,gap_type,target_field,source_hint,priority,status,reason,
     first_seen_at,last_seen_at,next_attempt_at,context,updated_at)
  select
    u.hkjc_event_id,'SHADOW_SOURCE_MISSING','fixture_detail','FOTMOB',
    case when u.kickoff_hkt <= now()+interval '24 hours' then 80 else 60 end,
    'OPEN','No matched FotMob shadow fixture captured yet',
    now(),now(),now(),
    jsonb_build_object('kickoff_hkt',u.kickoff_hkt,'tournament',u.tournament,'home',u.home_en,'away',u.away_en),
    now()
  from public.hkjc_upcoming_current u
  where u.kickoff_hkt between now()-interval '3 hours' and now()+interval '48 hours'
    and not exists (
      select 1 from public.phase15_source_shadow_current s
      where s.source_key='FOTMOB' and s.matched_hkjc_event_id=u.hkjc_event_id
    )
  on conflict (hkjc_event_id,gap_type,source_hint) do update
    set status='OPEN', last_seen_at=now(), priority=greatest(public.phase15_data_opportunity_queue.priority,excluded.priority),
        context=excluded.context, updated_at=now();
  get diagnostics v_rows = row_count;
  v_opened := v_opened + v_rows;

  insert into public.phase15_data_opportunity_queue
    (hkjc_event_id,gap_type,target_field,source_hint,priority,status,reason,
     first_seen_at,last_seen_at,next_attempt_at,context,updated_at)
  select
    u.hkjc_event_id,'INDEPENDENT_EVIDENCE_MISSING','external_evidence','AUTO_DISCOVERY',
    case when u.kickoff_hkt <= now()+interval '24 hours' then 95 else 75 end,
    'OPEN','No Forebet, model, or matched experimental shadow evidence',
    now(),now(),now(),
    jsonb_build_object('kickoff_hkt',u.kickoff_hkt,'tournament',u.tournament,'home',u.home_en,'away',u.away_en),
    now()
  from public.hkjc_upcoming_current u
  where u.kickoff_hkt between now()-interval '3 hours' and now()+interval '48 hours'
    and not exists (select 1 from public.forebet_predictions f where f.hkjc_event_id=u.hkjc_event_id)
    and not exists (select 1 from public.model_predictions m where m.hkjc_event_id=u.hkjc_event_id)
    and not exists (
      select 1 from public.phase15_source_shadow_current s
      where s.source_key='FOTMOB' and s.matched_hkjc_event_id=u.hkjc_event_id
    )
  on conflict (hkjc_event_id,gap_type,source_hint) do update
    set status='OPEN', last_seen_at=now(), priority=greatest(public.phase15_data_opportunity_queue.priority,excluded.priority),
        context=excluded.context, updated_at=now();
  get diagnostics v_rows = row_count;
  v_opened := v_opened + v_rows;

  update public.phase15_data_opportunity_queue q
  set status='RESOLVED', resolved_at=now(), updated_at=now(), last_result='Data became available'
  where q.status in ('OPEN','RETRY')
    and (
      (q.gap_type='PREDICTION_MISSING' and exists (select 1 from public.forebet_predictions f where f.hkjc_event_id=q.hkjc_event_id))
      or
      (q.gap_type='MODEL_MISSING' and exists (select 1 from public.model_predictions m where m.hkjc_event_id=q.hkjc_event_id))
      or
      (q.gap_type='HUMAN_FACTOR_MISSING' and exists (
        select 1 from public.human_factors_current h
        where h.hkjc_event_id=q.hkjc_event_id
          and (
            nullif(trim(coalesce(h.home_lineup,'')),'') is not null or
            nullif(trim(coalesce(h.away_lineup,'')),'') is not null or
            nullif(trim(coalesce(h.home_injuries,'')),'') is not null or
            nullif(trim(coalesce(h.away_injuries,'')),'') is not null or
            nullif(trim(coalesce(h.referee,'')),'') is not null
          )
      ))
      or
      (q.gap_type='SHADOW_SOURCE_MISSING' and exists (
        select 1 from public.phase15_source_shadow_current s
        where s.source_key='FOTMOB' and s.matched_hkjc_event_id=q.hkjc_event_id
      ))
      or
      (q.gap_type='INDEPENDENT_EVIDENCE_MISSING' and (
        exists (select 1 from public.forebet_predictions f where f.hkjc_event_id=q.hkjc_event_id)
        or exists (select 1 from public.model_predictions m where m.hkjc_event_id=q.hkjc_event_id)
        or exists (select 1 from public.phase15_source_shadow_current s where s.source_key='FOTMOB' and s.matched_hkjc_event_id=q.hkjc_event_id)
      ))
    );
  get diagnostics v_resolved = row_count;

  update public.phase15_source_registry r
  set last_probe_at=(select max(s.fetched_at) from public.phase15_source_shadow_current s where s.source_key='FOTMOB'),
      last_success_at=(select max(s.fetched_at) from public.phase15_source_shadow_current s where s.source_key='FOTMOB'),
      total_records=(select count(*) from public.phase15_source_shadow_current s where s.source_key='FOTMOB'),
      trust_score=least(0.79, 0.25 +
        least(0.30, (select count(*)::numeric/1000 from public.phase15_source_shadow_current s where s.source_key='FOTMOB')) +
        case when exists (select 1 from public.phase15_source_shadow_current s where s.source_key='FOTMOB' and s.matched_hkjc_event_id is not null) then 0.15 else 0 end
      ),
      updated_at=now()
  where r.source_key='FOTMOB'
    and exists (select 1 from public.phase15_source_shadow_current s where s.source_key='FOTMOB');

  insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
  values (
    'PHASE15_SOURCE_DISCOVERY','6h',
    jsonb_build_object(
      'active_sources',v_sources,
      'open_queue',(select count(*) from public.phase15_data_opportunity_queue where status in ('OPEN','RETRY')),
      'fotmob_shadow_rows',(select count(*) from public.phase15_source_shadow_current where source_key='FOTMOB'),
      'fotmob_matched_rows',(select count(*) from public.phase15_source_shadow_current where source_key='FOTMOB' and matched_hkjc_event_id is not null),
      'evidence_learned',v_learned
    )::text,
    case when (select count(*) from public.phase15_data_opportunity_queue where status='OPEN' and priority>=90)>0 then 'WARN' else 'OK' end,
    'Phase 1.5 gap-driven source discovery; experimental sources remain shadow-only until promoted.',
    now(),
    jsonb_build_object('run_id',v_run_id)
  );

  update public.phase15_discovery_runs
  set finished_at=now(),
      status=case when (select count(*) from public.phase15_data_opportunity_queue where status='OPEN' and priority>=90)>0 then 'WARN' else 'OK' end,
      sources_seen=v_sources,
      opportunities_opened=v_opened,
      opportunities_resolved=v_resolved,
      evidence_learned=v_learned,
      notes='Gap-driven discovery maintenance completed'
  where run_id=v_run_id;

  return jsonb_build_object(
    'run_id',v_run_id,
    'active_sources',v_sources,
    'queue_touches',v_opened,
    'resolved',v_resolved,
    'evidence_learned',v_learned,
    'open_queue',(select count(*) from public.phase15_data_opportunity_queue where status in ('OPEN','RETRY'))
  );
exception when others then
  if v_run_id is not null then
    update public.phase15_discovery_runs
      set finished_at=now(), status='FAILED', notes=sqlerrm
    where run_id=v_run_id;
  end if;
  raise;
end
$$;

revoke all on function private.ft_phase15_learn_exact_shadow() from public;
revoke all on function private.ft_phase15_discovery_maintenance() from public;
grant execute on function private.ft_phase15_learn_exact_shadow() to postgres, service_role;
grant execute on function private.ft_phase15_discovery_maintenance() to postgres, service_role;
