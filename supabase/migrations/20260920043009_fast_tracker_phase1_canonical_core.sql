
create schema if not exists private;
create schema if not exists api;

revoke all on schema private from public, anon, authenticated;
revoke all on schema api from public, anon, authenticated;
grant usage on schema private to service_role;
grant usage on schema api to service_role;

create table if not exists private.source_registry (
  source_key text primary key,
  display_name text not null,
  source_group text not null,
  phase smallint not null default 1 check (phase between 1 and 3),
  is_independent boolean not null default true,
  enabled boolean not null default true,
  notes text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists private.matches (
  hkjc_event_id text primary key,
  hkjc_match_id text,
  kickoff_hkt timestamptz,
  status text,
  tournament text,
  home_en text,
  away_en text,
  home_zh text,
  away_zh text,
  pools text,
  pool_status text,
  in_play boolean,
  selling boolean,
  fetched_at timestamptz,
  source_updated_at timestamptz,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists private_matches_kickoff_idx on private.matches(kickoff_hkt);
create index if not exists private_matches_active_idx on private.matches(selling, kickoff_hkt);

create table if not exists private.market_current (
  hkjc_event_id text not null references private.matches(hkjc_event_id) on delete cascade,
  source_key text not null references private.source_registry(source_key),
  market_key text not null,
  selection_key text not null,
  line_text text not null default '',
  odds numeric,
  captured_at timestamptz,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (hkjc_event_id, source_key, market_key, selection_key, line_text)
);

create table if not exists private.multisource_consensus_current (
  hkjc_event_id text primary key references private.matches(hkjc_event_id) on delete cascade,
  built_at timestamptz,
  external_fixture_id text,
  github_forebet_date date,
  github_forebet_time text,
  github_forebet_league text,
  github_forebet_home text,
  github_forebet_away text,
  home_away_explicit boolean,
  match_status text,
  match_reason text,
  candidate_count integer,
  our_forebet_home text,
  our_forebet_away text,
  hkjc_home text,
  hkjc_away text,
  hkjc_kickoff_hkt timestamptz,
  source_count_total integer,
  sources_total text[] not null default '{}',
  source_count_consensus integer,
  sources_consensus text[] not null default '{}',
  learned_alias_count integer,
  learned_aliases text[] not null default '{}',
  consensus_home numeric,
  consensus_draw numeric,
  consensus_away numeric,
  consensus_over25 numeric,
  consensus_under25 numeric,
  consensus_btts_yes numeric,
  consensus_btts_no numeric,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists multisource_built_at_idx
  on private.multisource_consensus_current(built_at desc);

create table if not exists private.prediction_evidence_current (
  hkjc_event_id text not null references private.matches(hkjc_event_id) on delete cascade,
  source_key text not null references private.source_registry(source_key),
  market_key text not null,
  source_updated_at timestamptz,
  status text,
  pick text,
  predicted_score text,
  prob_home numeric,
  prob_draw numeric,
  prob_away numeric,
  prob_over numeric,
  prob_under numeric,
  prob_yes numeric,
  prob_no numeric,
  xg_home numeric,
  xg_away numeric,
  avg_goals numeric,
  avg_corners numeric,
  source_count integer,
  source_members text[] not null default '{}',
  confidence numeric,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (hkjc_event_id, source_key, market_key)
);

create index if not exists prediction_evidence_event_idx
  on private.prediction_evidence_current(hkjc_event_id);
create index if not exists prediction_evidence_source_idx
  on private.prediction_evidence_current(source_key, market_key);

create table if not exists private.phase1_decision_current (
  hkjc_event_id text primary key references private.matches(hkjc_event_id) on delete cascade,
  decision text,
  market_key text,
  selection_key text,
  model_probability numeric,
  market_odds numeric,
  edge numeric,
  confidence numeric,
  reasons jsonb not null default '[]'::jsonb,
  engine_version text,
  calculated_at timestamptz,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists private.match_factors_current (
  hkjc_event_id text primary key references private.matches(hkjc_event_id) on delete cascade,
  factor_version text,
  lineup_signal jsonb not null default '{}'::jsonb,
  injury_signal jsonb not null default '{}'::jsonb,
  rest_travel_signal jsonb not null default '{}'::jsonb,
  motivation_signal jsonb not null default '{}'::jsonb,
  weather_pitch_signal jsonb not null default '{}'::jsonb,
  referee_signal jsonb not null default '{}'::jsonb,
  contradiction_signal jsonb not null default '{}'::jsonb,
  source_updated_at timestamptz,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists private.live_event_timeline (
  id bigint generated always as identity primary key,
  hkjc_event_id text not null references private.matches(hkjc_event_id) on delete cascade,
  occurred_at timestamptz not null,
  match_minute integer,
  event_type text not null,
  source text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists live_event_timeline_match_time_idx
  on private.live_event_timeline(hkjc_event_id, occurred_at);

alter table private.source_registry enable row level security;
alter table private.matches enable row level security;
alter table private.market_current enable row level security;
alter table private.multisource_consensus_current enable row level security;
alter table private.prediction_evidence_current enable row level security;
alter table private.phase1_decision_current enable row level security;
alter table private.match_factors_current enable row level security;
alter table private.live_event_timeline enable row level security;

create policy "service_role_all_source_registry" on private.source_registry
  for all to service_role using (true) with check (true);
create policy "service_role_all_matches" on private.matches
  for all to service_role using (true) with check (true);
create policy "service_role_all_market_current" on private.market_current
  for all to service_role using (true) with check (true);
create policy "service_role_all_multisource" on private.multisource_consensus_current
  for all to service_role using (true) with check (true);
create policy "service_role_all_prediction_evidence" on private.prediction_evidence_current
  for all to service_role using (true) with check (true);
create policy "service_role_all_phase1_decision" on private.phase1_decision_current
  for all to service_role using (true) with check (true);
create policy "service_role_all_match_factors" on private.match_factors_current
  for all to service_role using (true) with check (true);
create policy "service_role_all_live_timeline" on private.live_event_timeline
  for all to service_role using (true) with check (true);

grant select, insert, update, delete on all tables in schema private to service_role;
grant usage, select on all sequences in schema private to service_role;
alter default privileges in schema private
  revoke all on tables from anon, authenticated;
alter default privileges in schema private
  grant select, insert, update, delete on tables to service_role;
alter default privileges in schema private
  grant usage, select on sequences to service_role;

insert into private.source_registry
  (source_key, display_name, source_group, phase, is_independent, enabled, notes)
values
  ('HKJC','HKJC','market_authority',1,false,true,'Canonical active betting universe and primary market'),
  ('FOREBET','Forebet','prediction',1,true,true,'External prediction model'),
  ('MULTISOURCE','Multi-source Intelligence Layer','consensus',1,true,true,'Former Multibetter aggregate; not a separate product'),
  ('DC','Dixon-Coles','stat_model',1,true,true,'Independent shadow model'),
  ('PI','Pi Ratings','stat_model',1,true,true,'Independent rating model'),
  ('FORM','Form Model','stat_model',1,true,true,'Independent form model'),
  ('BET365','Bet365','market_benchmark',1,true,true,'Secondary external market benchmark'),
  ('APWIN','APWin','prediction',1,true,true,'Fallback / component prediction source')
on conflict (source_key) do update set
  display_name=excluded.display_name,
  source_group=excluded.source_group,
  phase=excluded.phase,
  is_independent=excluded.is_independent,
  enabled=excluded.enabled,
  notes=excluded.notes,
  updated_at=now();

create or replace function public.ft_internal_refresh_phase1_core()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
  v_matches integer := 0;
  v_markets integer := 0;
  v_evidence integer := 0;
begin
  insert into private.matches (
    hkjc_event_id,hkjc_match_id,kickoff_hkt,status,tournament,
    home_en,away_en,home_zh,away_zh,pools,pool_status,in_play,selling,
    fetched_at,source_updated_at,raw,updated_at
  )
  select
    m.hkjc_event_id,m.hkjc_match_id,m.kickoff_hkt,m.status,m.tournament,
    m.home_en,m.away_en,m.home_zh,m.away_zh,m.pools,m.pool_status,m.in_play,m.selling,
    m.fetched_at,m.source_updated_at,m.raw,now()
  from public.matches m
  on conflict (hkjc_event_id) do update set
    hkjc_match_id=excluded.hkjc_match_id,
    kickoff_hkt=excluded.kickoff_hkt,
    status=excluded.status,
    tournament=excluded.tournament,
    home_en=excluded.home_en,
    away_en=excluded.away_en,
    home_zh=excluded.home_zh,
    away_zh=excluded.away_zh,
    pools=excluded.pools,
    pool_status=excluded.pool_status,
    in_play=excluded.in_play,
    selling=excluded.selling,
    fetched_at=excluded.fetched_at,
    source_updated_at=excluded.source_updated_at,
    raw=excluded.raw,
    updated_at=now();
  get diagnostics v_matches = row_count;

  insert into private.market_current
    (hkjc_event_id,source_key,market_key,selection_key,line_text,odds,captured_at,raw,updated_at)
  select h.hkjc_event_id,'HKJC','1X2',x.selection_key,'',x.odds,h.odds_updated_at,h.raw,now()
  from public.hkjc_odds_current h
  cross join lateral (values
    ('HOME',h.had_home),
    ('DRAW',h.had_draw),
    ('AWAY',h.had_away)
  ) as x(selection_key,odds)
  on conflict (hkjc_event_id,source_key,market_key,selection_key,line_text)
  do update set odds=excluded.odds,captured_at=excluded.captured_at,raw=excluded.raw,updated_at=now();

  insert into private.market_current
    (hkjc_event_id,source_key,market_key,selection_key,line_text,odds,captured_at,raw,updated_at)
  select h.hkjc_event_id,'HKJC','GOALS_TOTAL',x.selection_key,coalesce(h.hil_line,''),x.odds,h.odds_updated_at,h.raw,now()
  from public.hkjc_odds_current h
  cross join lateral (values
    ('OVER',h.hil_over),
    ('UNDER',h.hil_under)
  ) as x(selection_key,odds)
  on conflict (hkjc_event_id,source_key,market_key,selection_key,line_text)
  do update set odds=excluded.odds,captured_at=excluded.captured_at,raw=excluded.raw,updated_at=now();

  insert into private.market_current
    (hkjc_event_id,source_key,market_key,selection_key,line_text,odds,captured_at,raw,updated_at)
  select h.hkjc_event_id,'HKJC','CORNERS_TOTAL',x.selection_key,coalesce(h.chl_line,''),x.odds,h.odds_updated_at,h.raw,now()
  from public.hkjc_odds_current h
  cross join lateral (values
    ('OVER',h.chl_over),
    ('UNDER',h.chl_under)
  ) as x(selection_key,odds)
  on conflict (hkjc_event_id,source_key,market_key,selection_key,line_text)
  do update set odds=excluded.odds,captured_at=excluded.captured_at,raw=excluded.raw,updated_at=now();

  select count(*)::integer into v_markets from private.market_current;

  insert into private.prediction_evidence_current (
    hkjc_event_id,source_key,market_key,source_updated_at,status,pick,predicted_score,
    prob_home,prob_draw,prob_away,avg_goals,raw,updated_at
  )
  select
    f.hkjc_event_id,'FOREBET','1X2',f.source_updated_at,f.forebet_status,
    f.prediction_1x2,f.predicted_score,f.prob_home,f.prob_draw,f.prob_away,f.avg_goals,
    jsonb_build_object('forebet_status',f.forebet_status),now()
  from public.forebet_effective_v f
  on conflict (hkjc_event_id,source_key,market_key) do update set
    source_updated_at=excluded.source_updated_at,status=excluded.status,pick=excluded.pick,
    predicted_score=excluded.predicted_score,prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,
    prob_away=excluded.prob_away,avg_goals=excluded.avg_goals,raw=excluded.raw,updated_at=now();

  insert into private.prediction_evidence_current (
    hkjc_event_id,source_key,market_key,source_updated_at,status,pick,predicted_score,
    prob_over,prob_under,avg_goals,raw,updated_at
  )
  select
    f.hkjc_event_id,'FOREBET','OU25',f.source_updated_at,f.forebet_status,
    f.prediction_ou25,f.ou_predicted_score,f.prob_over25,f.prob_under25,f.avg_goals,
    jsonb_build_object('forebet_status',f.forebet_status),now()
  from public.forebet_effective_v f
  on conflict (hkjc_event_id,source_key,market_key) do update set
    source_updated_at=excluded.source_updated_at,status=excluded.status,pick=excluded.pick,
    predicted_score=excluded.predicted_score,prob_over=excluded.prob_over,prob_under=excluded.prob_under,
    avg_goals=excluded.avg_goals,raw=excluded.raw,updated_at=now();

  insert into private.prediction_evidence_current (
    hkjc_event_id,source_key,market_key,source_updated_at,status,pick,predicted_score,
    prob_over,prob_under,avg_corners,raw,updated_at
  )
  select
    f.hkjc_event_id,'FOREBET','CORNERS95',f.source_updated_at,f.forebet_status,
    f.corner_prediction,f.corner_predicted_score,f.corner_prob_over95,f.corner_prob_under95,f.avg_corners,
    jsonb_build_object('forebet_status',f.forebet_status),now()
  from public.forebet_effective_v f
  on conflict (hkjc_event_id,source_key,market_key) do update set
    source_updated_at=excluded.source_updated_at,status=excluded.status,pick=excluded.pick,
    predicted_score=excluded.predicted_score,prob_over=excluded.prob_over,prob_under=excluded.prob_under,
    avg_corners=excluded.avg_corners,raw=excluded.raw,updated_at=now();

  insert into private.prediction_evidence_current (
    hkjc_event_id,source_key,market_key,source_updated_at,status,
    prob_home,prob_draw,prob_away,xg_home,xg_away,raw,updated_at
  )
  select
    m.hkjc_event_id,'DC','1X2',m.fetched_at,m.quality,
    m.dc_prob_home,m.dc_prob_draw,m.dc_prob_away,m.dc_xg_home,m.dc_xg_away,m.raw,now()
  from public.model_predictions m
  on conflict (hkjc_event_id,source_key,market_key) do update set
    source_updated_at=excluded.source_updated_at,status=excluded.status,
    prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
    xg_home=excluded.xg_home,xg_away=excluded.xg_away,raw=excluded.raw,updated_at=now();

  insert into private.prediction_evidence_current (
    hkjc_event_id,source_key,market_key,source_updated_at,status,
    prob_home,prob_draw,prob_away,raw,updated_at
  )
  select
    m.hkjc_event_id,'PI','1X2',m.fetched_at,m.quality,
    m.pi_prob_home,m.pi_prob_draw,m.pi_prob_away,m.raw,now()
  from public.model_predictions m
  on conflict (hkjc_event_id,source_key,market_key) do update set
    source_updated_at=excluded.source_updated_at,status=excluded.status,
    prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
    raw=excluded.raw,updated_at=now();

  insert into private.prediction_evidence_current (
    hkjc_event_id,source_key,market_key,source_updated_at,status,
    prob_home,prob_draw,prob_away,xg_home,xg_away,raw,updated_at
  )
  select
    f.hkjc_event_id,'FORM','1X2',f.fetched_at,f.quality,
    f.form_prob_home,f.form_prob_draw,f.form_prob_away,f.form_xg_home,f.form_xg_away,f.raw,now()
  from public.form_predictions f
  on conflict (hkjc_event_id,source_key,market_key) do update set
    source_updated_at=excluded.source_updated_at,status=excluded.status,
    prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
    xg_home=excluded.xg_home,xg_away=excluded.xg_away,raw=excluded.raw,updated_at=now();

  insert into private.prediction_evidence_current (
    hkjc_event_id,source_key,market_key,source_updated_at,status,
    prob_home,prob_draw,prob_away,source_count,source_members,raw,updated_at
  )
  select
    x.hkjc_event_id,'MULTISOURCE','1X2',x.built_at,x.match_status,
    x.consensus_home,x.consensus_draw,x.consensus_away,x.source_count_consensus,x.sources_consensus,x.raw,now()
  from private.multisource_consensus_current x
  on conflict (hkjc_event_id,source_key,market_key) do update set
    source_updated_at=excluded.source_updated_at,status=excluded.status,
    prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
    source_count=excluded.source_count,source_members=excluded.source_members,raw=excluded.raw,updated_at=now();

  insert into private.prediction_evidence_current (
    hkjc_event_id,source_key,market_key,source_updated_at,status,
    prob_over,prob_under,source_count,source_members,raw,updated_at
  )
  select
    x.hkjc_event_id,'MULTISOURCE','OU25',x.built_at,x.match_status,
    x.consensus_over25,x.consensus_under25,x.source_count_consensus,x.sources_consensus,x.raw,now()
  from private.multisource_consensus_current x
  where x.consensus_over25 is not null or x.consensus_under25 is not null
  on conflict (hkjc_event_id,source_key,market_key) do update set
    source_updated_at=excluded.source_updated_at,status=excluded.status,
    prob_over=excluded.prob_over,prob_under=excluded.prob_under,
    source_count=excluded.source_count,source_members=excluded.source_members,raw=excluded.raw,updated_at=now();

  insert into private.prediction_evidence_current (
    hkjc_event_id,source_key,market_key,source_updated_at,status,
    prob_yes,prob_no,source_count,source_members,raw,updated_at
  )
  select
    x.hkjc_event_id,'MULTISOURCE','BTTS',x.built_at,x.match_status,
    x.consensus_btts_yes,x.consensus_btts_no,x.source_count_consensus,x.sources_consensus,x.raw,now()
  from private.multisource_consensus_current x
  where x.consensus_btts_yes is not null or x.consensus_btts_no is not null
  on conflict (hkjc_event_id,source_key,market_key) do update set
    source_updated_at=excluded.source_updated_at,status=excluded.status,
    prob_yes=excluded.prob_yes,prob_no=excluded.prob_no,
    source_count=excluded.source_count,source_members=excluded.source_members,raw=excluded.raw,updated_at=now();

  select count(*)::integer into v_evidence from private.prediction_evidence_current;

  return jsonb_build_object(
    'matches',v_matches,
    'market_rows',v_markets,
    'evidence_rows',v_evidence
  );
end
$$;

revoke all on function public.ft_internal_refresh_phase1_core() from public, anon, authenticated;
grant execute on function public.ft_internal_refresh_phase1_core() to service_role;

create or replace function public.ft_internal_upsert_multisource(payload jsonb)
returns integer
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
  v_count integer := 0;
begin
  if payload is null or jsonb_typeof(payload) <> 'array' then
    raise exception 'payload must be a JSON array';
  end if;

  insert into private.matches (
    hkjc_event_id,hkjc_match_id,kickoff_hkt,status,tournament,
    home_en,away_en,home_zh,away_zh,pools,pool_status,in_play,selling,
    fetched_at,source_updated_at,raw,updated_at
  )
  select
    m.hkjc_event_id,m.hkjc_match_id,m.kickoff_hkt,m.status,m.tournament,
    m.home_en,m.away_en,m.home_zh,m.away_zh,m.pools,m.pool_status,m.in_play,m.selling,
    m.fetched_at,m.source_updated_at,m.raw,now()
  from public.matches m
  join (
    select distinct hkjc_event_id
    from jsonb_to_recordset(payload) as j(hkjc_event_id text)
    where hkjc_event_id is not null
  ) x using (hkjc_event_id)
  on conflict (hkjc_event_id) do update set
    hkjc_match_id=excluded.hkjc_match_id,kickoff_hkt=excluded.kickoff_hkt,status=excluded.status,
    tournament=excluded.tournament,home_en=excluded.home_en,away_en=excluded.away_en,
    home_zh=excluded.home_zh,away_zh=excluded.away_zh,pools=excluded.pools,pool_status=excluded.pool_status,
    in_play=excluded.in_play,selling=excluded.selling,fetched_at=excluded.fetched_at,
    source_updated_at=excluded.source_updated_at,raw=excluded.raw,updated_at=now();

  insert into private.multisource_consensus_current (
    hkjc_event_id,built_at,external_fixture_id,github_forebet_date,github_forebet_time,
    github_forebet_league,github_forebet_home,github_forebet_away,home_away_explicit,
    match_status,match_reason,candidate_count,our_forebet_home,our_forebet_away,
    hkjc_home,hkjc_away,hkjc_kickoff_hkt,source_count_total,sources_total,
    source_count_consensus,sources_consensus,learned_alias_count,learned_aliases,
    consensus_home,consensus_draw,consensus_away,consensus_over25,consensus_under25,
    consensus_btts_yes,consensus_btts_no,raw,updated_at
  )
  select
    j.hkjc_event_id,j.built_at,j.external_fixture_id,j.github_forebet_date,j.github_forebet_time,
    j.github_forebet_league,j.github_forebet_home,j.github_forebet_away,j.home_away_explicit,
    j.match_status,j.match_reason,j.candidate_count,j.our_forebet_home,j.our_forebet_away,
    j.hkjc_home,j.hkjc_away,j.hkjc_kickoff_hkt,j.source_count_total,coalesce(j.sources_total,'{}'::text[]),
    j.source_count_consensus,coalesce(j.sources_consensus,'{}'::text[]),j.learned_alias_count,
    coalesce(j.learned_aliases,'{}'::text[]),j.consensus_home,j.consensus_draw,j.consensus_away,
    j.consensus_over25,j.consensus_under25,j.consensus_btts_yes,j.consensus_btts_no,
    coalesce(j.raw,'{}'::jsonb),now()
  from jsonb_to_recordset(payload) as j(
    hkjc_event_id text,
    built_at timestamptz,
    external_fixture_id text,
    github_forebet_date date,
    github_forebet_time text,
    github_forebet_league text,
    github_forebet_home text,
    github_forebet_away text,
    home_away_explicit boolean,
    match_status text,
    match_reason text,
    candidate_count integer,
    our_forebet_home text,
    our_forebet_away text,
    hkjc_home text,
    hkjc_away text,
    hkjc_kickoff_hkt timestamptz,
    source_count_total integer,
    sources_total text[],
    source_count_consensus integer,
    sources_consensus text[],
    learned_alias_count integer,
    learned_aliases text[],
    consensus_home numeric,
    consensus_draw numeric,
    consensus_away numeric,
    consensus_over25 numeric,
    consensus_under25 numeric,
    consensus_btts_yes numeric,
    consensus_btts_no numeric,
    raw jsonb
  )
  where j.hkjc_event_id is not null
  on conflict (hkjc_event_id) do update set
    built_at=excluded.built_at,external_fixture_id=excluded.external_fixture_id,
    github_forebet_date=excluded.github_forebet_date,github_forebet_time=excluded.github_forebet_time,
    github_forebet_league=excluded.github_forebet_league,github_forebet_home=excluded.github_forebet_home,
    github_forebet_away=excluded.github_forebet_away,home_away_explicit=excluded.home_away_explicit,
    match_status=excluded.match_status,match_reason=excluded.match_reason,candidate_count=excluded.candidate_count,
    our_forebet_home=excluded.our_forebet_home,our_forebet_away=excluded.our_forebet_away,
    hkjc_home=excluded.hkjc_home,hkjc_away=excluded.hkjc_away,hkjc_kickoff_hkt=excluded.hkjc_kickoff_hkt,
    source_count_total=excluded.source_count_total,sources_total=excluded.sources_total,
    source_count_consensus=excluded.source_count_consensus,sources_consensus=excluded.sources_consensus,
    learned_alias_count=excluded.learned_alias_count,learned_aliases=excluded.learned_aliases,
    consensus_home=excluded.consensus_home,consensus_draw=excluded.consensus_draw,
    consensus_away=excluded.consensus_away,consensus_over25=excluded.consensus_over25,
    consensus_under25=excluded.consensus_under25,consensus_btts_yes=excluded.consensus_btts_yes,
    consensus_btts_no=excluded.consensus_btts_no,raw=excluded.raw,updated_at=now();

  get diagnostics v_count = row_count;
  perform public.ft_internal_refresh_phase1_core();
  return v_count;
end
$$;

revoke all on function public.ft_internal_upsert_multisource(jsonb) from public, anon, authenticated;
grant execute on function public.ft_internal_upsert_multisource(jsonb) to service_role;

create or replace view api.phase1_match_intelligence_v
with (security_invoker = true)
as
select
  m.hkjc_event_id,
  m.kickoff_hkt,
  m.status,
  m.tournament,
  m.home_en,
  m.away_en,
  m.home_zh,
  m.away_zh,
  m.in_play,
  m.selling,
  mh.odds as hkjc_home_odds,
  md.odds as hkjc_draw_odds,
  ma.odds as hkjc_away_odds,
  case when mh.odds > 0 and md.odds > 0 and ma.odds > 0 then
    (1/mh.odds) / ((1/mh.odds)+(1/md.odds)+(1/ma.odds)) * 100
  end as hkjc_novig_home,
  case when mh.odds > 0 and md.odds > 0 and ma.odds > 0 then
    (1/md.odds) / ((1/mh.odds)+(1/md.odds)+(1/ma.odds)) * 100
  end as hkjc_novig_draw,
  case when mh.odds > 0 and md.odds > 0 and ma.odds > 0 then
    (1/ma.odds) / ((1/mh.odds)+(1/md.odds)+(1/ma.odds)) * 100
  end as hkjc_novig_away,
  fb.prob_home as forebet_home,
  fb.prob_draw as forebet_draw,
  fb.prob_away as forebet_away,
  dc.prob_home as dc_home,
  dc.prob_draw as dc_draw,
  dc.prob_away as dc_away,
  pi.prob_home as pi_home,
  pi.prob_draw as pi_draw,
  pi.prob_away as pi_away,
  fm.prob_home as form_home,
  fm.prob_draw as form_draw,
  fm.prob_away as form_away,
  ms.prob_home as multisource_home,
  ms.prob_draw as multisource_draw,
  ms.prob_away as multisource_away,
  ms.source_count as multisource_count,
  ms.source_members as multisource_sources,
  case when mh.odds is not null and ms.prob_home is not null then (mh.odds*ms.prob_home/100)-1 end as multisource_edge_home,
  case when md.odds is not null and ms.prob_draw is not null then (md.odds*ms.prob_draw/100)-1 end as multisource_edge_draw,
  case when ma.odds is not null and ms.prob_away is not null then (ma.odds*ms.prob_away/100)-1 end as multisource_edge_away,
  case when mh.odds is not null and fb.prob_home is not null then (mh.odds*fb.prob_home/100)-1 end as forebet_edge_home,
  case when md.odds is not null and fb.prob_draw is not null then (md.odds*fb.prob_draw/100)-1 end as forebet_edge_draw,
  case when ma.odds is not null and fb.prob_away is not null then (ma.odds*fb.prob_away/100)-1 end as forebet_edge_away,
  greatest(fb.source_updated_at,dc.source_updated_at,pi.source_updated_at,fm.source_updated_at,ms.source_updated_at,m.source_updated_at) as data_updated_at
from private.matches m
left join private.market_current mh
  on mh.hkjc_event_id=m.hkjc_event_id and mh.source_key='HKJC' and mh.market_key='1X2' and mh.selection_key='HOME'
left join private.market_current md
  on md.hkjc_event_id=m.hkjc_event_id and md.source_key='HKJC' and md.market_key='1X2' and md.selection_key='DRAW'
left join private.market_current ma
  on ma.hkjc_event_id=m.hkjc_event_id and ma.source_key='HKJC' and ma.market_key='1X2' and ma.selection_key='AWAY'
left join private.prediction_evidence_current fb
  on fb.hkjc_event_id=m.hkjc_event_id and fb.source_key='FOREBET' and fb.market_key='1X2'
left join private.prediction_evidence_current dc
  on dc.hkjc_event_id=m.hkjc_event_id and dc.source_key='DC' and dc.market_key='1X2'
left join private.prediction_evidence_current pi
  on pi.hkjc_event_id=m.hkjc_event_id and pi.source_key='PI' and pi.market_key='1X2'
left join private.prediction_evidence_current fm
  on fm.hkjc_event_id=m.hkjc_event_id and fm.source_key='FORM' and fm.market_key='1X2'
left join private.prediction_evidence_current ms
  on ms.hkjc_event_id=m.hkjc_event_id and ms.source_key='MULTISOURCE' and ms.market_key='1X2'
where m.selling is true;

revoke all on api.phase1_match_intelligence_v from public, anon, authenticated;
grant select on api.phase1_match_intelligence_v to service_role;

comment on schema private is
  'Fast Tracker 2026 internal canonical core. Not app-facing.';
comment on schema api is
  'Fast Tracker 2026 app-facing contract layer. Exposure/grants are opt-in.';
comment on table private.multisource_consensus_current is
  'Multi-source Intelligence Layer (formerly Multibetter) consensus keyed by HKJC event id.';
