
alter table private.source_registry
  add column if not exists decision_enabled boolean not null default false;

create or replace function private.normalize_prediction_probabilities()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
declare
  s numeric;
begin
  if new.prob_home is not null and new.prob_home > 1 then new.prob_home := new.prob_home / 100.0; end if;
  if new.prob_draw is not null and new.prob_draw > 1 then new.prob_draw := new.prob_draw / 100.0; end if;
  if new.prob_away is not null and new.prob_away > 1 then new.prob_away := new.prob_away / 100.0; end if;
  if new.prob_over is not null and new.prob_over > 1 then new.prob_over := new.prob_over / 100.0; end if;
  if new.prob_under is not null and new.prob_under > 1 then new.prob_under := new.prob_under / 100.0; end if;
  if new.prob_yes is not null and new.prob_yes > 1 then new.prob_yes := new.prob_yes / 100.0; end if;
  if new.prob_no is not null and new.prob_no > 1 then new.prob_no := new.prob_no / 100.0; end if;

  if new.prob_home is not null and new.prob_draw is not null and new.prob_away is not null then
    s := new.prob_home + new.prob_draw + new.prob_away;
    if s > 0 then
      new.prob_home := new.prob_home / s;
      new.prob_draw := new.prob_draw / s;
      new.prob_away := new.prob_away / s;
    end if;
  end if;

  if new.prob_over is not null and new.prob_under is not null then
    s := new.prob_over + new.prob_under;
    if s > 0 then
      new.prob_over := new.prob_over / s;
      new.prob_under := new.prob_under / s;
    end if;
  end if;

  if new.prob_yes is not null and new.prob_no is not null then
    s := new.prob_yes + new.prob_no;
    if s > 0 then
      new.prob_yes := new.prob_yes / s;
      new.prob_no := new.prob_no / s;
    end if;
  end if;

  return new;
end
$$;

drop trigger if exists normalize_prediction_probabilities_trg
  on private.prediction_evidence_current;
create trigger normalize_prediction_probabilities_trg
before insert or update on private.prediction_evidence_current
for each row execute function private.normalize_prediction_probabilities();

update private.prediction_evidence_current
set prob_home = case when prob_home > 1 then prob_home/100.0 else prob_home end,
    prob_draw = case when prob_draw > 1 then prob_draw/100.0 else prob_draw end,
    prob_away = case when prob_away > 1 then prob_away/100.0 else prob_away end,
    prob_over = case when prob_over > 1 then prob_over/100.0 else prob_over end,
    prob_under = case when prob_under > 1 then prob_under/100.0 else prob_under end,
    prob_yes = case when prob_yes > 1 then prob_yes/100.0 else prob_yes end,
    prob_no = case when prob_no > 1 then prob_no/100.0 else prob_no end;

alter table private.prediction_evidence_current
  drop constraint if exists prediction_prob_home_range,
  drop constraint if exists prediction_prob_draw_range,
  drop constraint if exists prediction_prob_away_range,
  drop constraint if exists prediction_prob_over_range,
  drop constraint if exists prediction_prob_under_range,
  drop constraint if exists prediction_prob_yes_range,
  drop constraint if exists prediction_prob_no_range;

alter table private.prediction_evidence_current
  add constraint prediction_prob_home_range check (prob_home is null or prob_home between 0 and 1),
  add constraint prediction_prob_draw_range check (prob_draw is null or prob_draw between 0 and 1),
  add constraint prediction_prob_away_range check (prob_away is null or prob_away between 0 and 1),
  add constraint prediction_prob_over_range check (prob_over is null or prob_over between 0 and 1),
  add constraint prediction_prob_under_range check (prob_under is null or prob_under between 0 and 1),
  add constraint prediction_prob_yes_range check (prob_yes is null or prob_yes between 0 and 1),
  add constraint prediction_prob_no_range check (prob_no is null or prob_no between 0 and 1);

create table if not exists private.prematch_prediction_snapshot (
  hkjc_event_id text not null references private.matches(hkjc_event_id) on delete cascade,
  source_key text not null references private.source_registry(source_key),
  market_key text not null,
  kickoff_hkt timestamptz,
  captured_at timestamptz not null,
  source_updated_at timestamptz,
  source_status text,
  prob_home numeric,
  prob_draw numeric,
  prob_away numeric,
  prob_over numeric,
  prob_under numeric,
  prob_yes numeric,
  prob_no numeric,
  xg_home numeric,
  xg_away numeric,
  market_odds_home numeric,
  market_odds_draw numeric,
  market_odds_away numeric,
  raw jsonb not null default '{}'::jsonb,
  primary key (hkjc_event_id, source_key, market_key)
);

create index if not exists prematch_snapshot_kickoff_idx
  on private.prematch_prediction_snapshot(kickoff_hkt);
create index if not exists prematch_snapshot_source_idx
  on private.prematch_prediction_snapshot(source_key, market_key);

create table if not exists private.match_results (
  hkjc_event_id text primary key references private.matches(hkjc_event_id) on delete cascade,
  match_id text,
  kickoff_hkt timestamptz,
  tournament text,
  home text,
  away text,
  home_goals integer,
  away_goals integer,
  outcome text check (outcome in ('H','D','A')),
  payout_confirmed boolean,
  fetched_at timestamptz,
  raw jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists match_results_kickoff_idx
  on private.match_results(kickoff_hkt);

create table if not exists private.validation_score (
  hkjc_event_id text not null references private.match_results(hkjc_event_id) on delete cascade,
  source_key text not null references private.source_registry(source_key),
  market_key text not null,
  captured_at timestamptz not null,
  outcome text not null,
  rps numeric,
  brier numeric,
  logloss numeric,
  top_pick text,
  top_pick_correct boolean,
  best_edge_selection text,
  best_edge numeric,
  positive_edge_bet boolean,
  realized_return numeric,
  calculated_at timestamptz not null default now(),
  raw jsonb not null default '{}'::jsonb,
  primary key (hkjc_event_id, source_key, market_key)
);

create table if not exists private.validation_summary (
  source_key text not null references private.source_registry(source_key),
  market_key text not null,
  settled_matches integer not null default 0,
  avg_rps numeric,
  avg_brier numeric,
  avg_logloss numeric,
  top_pick_accuracy numeric,
  positive_edge_bets integer not null default 0,
  positive_edge_roi numeric,
  validation_state text not null default 'NO_SAMPLE',
  as_of timestamptz not null default now(),
  raw jsonb not null default '{}'::jsonb,
  primary key (source_key, market_key)
);

alter table private.prematch_prediction_snapshot enable row level security;
alter table private.match_results enable row level security;
alter table private.validation_score enable row level security;
alter table private.validation_summary enable row level security;

drop policy if exists "service_role_all_prematch_snapshot" on private.prematch_prediction_snapshot;
create policy "service_role_all_prematch_snapshot"
on private.prematch_prediction_snapshot for all to service_role using (true) with check (true);

drop policy if exists "service_role_all_match_results" on private.match_results;
create policy "service_role_all_match_results"
on private.match_results for all to service_role using (true) with check (true);

drop policy if exists "service_role_all_validation_score" on private.validation_score;
create policy "service_role_all_validation_score"
on private.validation_score for all to service_role using (true) with check (true);

drop policy if exists "service_role_all_validation_summary" on private.validation_summary;
create policy "service_role_all_validation_summary"
on private.validation_summary for all to service_role using (true) with check (true);

grant select, insert, update, delete on
  private.prematch_prediction_snapshot,
  private.match_results,
  private.validation_score,
  private.validation_summary
to service_role;

create or replace function public.ft_internal_capture_prematch()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
  v_evidence integer := 0;
  v_market integer := 0;
begin
  insert into private.prematch_prediction_snapshot (
    hkjc_event_id,source_key,market_key,kickoff_hkt,captured_at,source_updated_at,source_status,
    prob_home,prob_draw,prob_away,prob_over,prob_under,prob_yes,prob_no,
    xg_home,xg_away,market_odds_home,market_odds_draw,market_odds_away,raw
  )
  select
    e.hkjc_event_id,e.source_key,e.market_key,m.kickoff_hkt,now(),e.source_updated_at,e.status,
    e.prob_home,e.prob_draw,e.prob_away,e.prob_over,e.prob_under,e.prob_yes,e.prob_no,
    e.xg_home,e.xg_away,
    mh.odds,md.odds,ma.odds,
    jsonb_build_object('evidence',e.raw,'snapshot_kind','canonical_pre_kickoff')
  from private.prediction_evidence_current e
  join private.matches m on m.hkjc_event_id=e.hkjc_event_id
  left join private.market_current mh
    on mh.hkjc_event_id=e.hkjc_event_id and mh.source_key='HKJC' and mh.market_key='1X2' and mh.selection_key='HOME'
  left join private.market_current md
    on md.hkjc_event_id=e.hkjc_event_id and md.source_key='HKJC' and md.market_key='1X2' and md.selection_key='DRAW'
  left join private.market_current ma
    on ma.hkjc_event_id=e.hkjc_event_id and ma.source_key='HKJC' and ma.market_key='1X2' and ma.selection_key='AWAY'
  where m.kickoff_hkt > now()
  on conflict (hkjc_event_id,source_key,market_key) do update set
    kickoff_hkt=excluded.kickoff_hkt,
    captured_at=excluded.captured_at,
    source_updated_at=excluded.source_updated_at,
    source_status=excluded.source_status,
    prob_home=excluded.prob_home,
    prob_draw=excluded.prob_draw,
    prob_away=excluded.prob_away,
    prob_over=excluded.prob_over,
    prob_under=excluded.prob_under,
    prob_yes=excluded.prob_yes,
    prob_no=excluded.prob_no,
    xg_home=excluded.xg_home,
    xg_away=excluded.xg_away,
    market_odds_home=excluded.market_odds_home,
    market_odds_draw=excluded.market_odds_draw,
    market_odds_away=excluded.market_odds_away,
    raw=excluded.raw;
  get diagnostics v_evidence = row_count;

  insert into private.prematch_prediction_snapshot (
    hkjc_event_id,source_key,market_key,kickoff_hkt,captured_at,source_updated_at,source_status,
    prob_home,prob_draw,prob_away,
    market_odds_home,market_odds_draw,market_odds_away,raw
  )
  select
    m.hkjc_event_id,'HKJC','1X2',m.kickoff_hkt,now(),
    greatest(mh.captured_at,md.captured_at,ma.captured_at),'MARKET_NOVIG',
    (1/mh.odds)/((1/mh.odds)+(1/md.odds)+(1/ma.odds)),
    (1/md.odds)/((1/mh.odds)+(1/md.odds)+(1/ma.odds)),
    (1/ma.odds)/((1/mh.odds)+(1/md.odds)+(1/ma.odds)),
    mh.odds,md.odds,ma.odds,
    jsonb_build_object('snapshot_kind','hkjc_novig_market')
  from private.matches m
  join private.market_current mh
    on mh.hkjc_event_id=m.hkjc_event_id and mh.source_key='HKJC' and mh.market_key='1X2' and mh.selection_key='HOME'
  join private.market_current md
    on md.hkjc_event_id=m.hkjc_event_id and md.source_key='HKJC' and md.market_key='1X2' and md.selection_key='DRAW'
  join private.market_current ma
    on ma.hkjc_event_id=m.hkjc_event_id and ma.source_key='HKJC' and ma.market_key='1X2' and ma.selection_key='AWAY'
  where m.kickoff_hkt > now()
    and mh.odds > 1 and md.odds > 1 and ma.odds > 1
  on conflict (hkjc_event_id,source_key,market_key) do update set
    kickoff_hkt=excluded.kickoff_hkt,
    captured_at=excluded.captured_at,
    source_updated_at=excluded.source_updated_at,
    source_status=excluded.source_status,
    prob_home=excluded.prob_home,
    prob_draw=excluded.prob_draw,
    prob_away=excluded.prob_away,
    market_odds_home=excluded.market_odds_home,
    market_odds_draw=excluded.market_odds_draw,
    market_odds_away=excluded.market_odds_away,
    raw=excluded.raw;
  get diagnostics v_market = row_count;

  return jsonb_build_object('evidence_snapshots',v_evidence,'market_snapshots',v_market);
end
$$;

revoke all on function public.ft_internal_capture_prematch() from public, anon, authenticated;
grant execute on function public.ft_internal_capture_prematch() to service_role;

create or replace function public.ft_internal_upsert_results(payload jsonb)
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
    hkjc_event_id,hkjc_match_id,kickoff_hkt,status,tournament,home_en,away_en,
    selling,in_play,raw,updated_at
  )
  select
    j.hkjc_event_id,j.match_id,j.kickoff_hkt,'RESULT',j.tournament,j.home,j.away,
    false,false,coalesce(j.raw,'{}'::jsonb),now()
  from jsonb_to_recordset(payload) as j(
    hkjc_event_id text, match_id text, kickoff_hkt timestamptz, tournament text,
    home text, away text, home_goals integer, away_goals integer,
    outcome text, payout_confirmed boolean, fetched_at timestamptz, raw jsonb
  )
  where j.hkjc_event_id is not null
  on conflict (hkjc_event_id) do update set
    hkjc_match_id=coalesce(private.matches.hkjc_match_id,excluded.hkjc_match_id),
    kickoff_hkt=coalesce(private.matches.kickoff_hkt,excluded.kickoff_hkt),
    tournament=coalesce(private.matches.tournament,excluded.tournament),
    home_en=coalesce(private.matches.home_en,excluded.home_en),
    away_en=coalesce(private.matches.away_en,excluded.away_en),
    updated_at=now();

  insert into private.match_results (
    hkjc_event_id,match_id,kickoff_hkt,tournament,home,away,
    home_goals,away_goals,outcome,payout_confirmed,fetched_at,raw,updated_at
  )
  select
    j.hkjc_event_id,j.match_id,j.kickoff_hkt,j.tournament,j.home,j.away,
    j.home_goals,j.away_goals,j.outcome,j.payout_confirmed,j.fetched_at,
    coalesce(j.raw,'{}'::jsonb),now()
  from jsonb_to_recordset(payload) as j(
    hkjc_event_id text, match_id text, kickoff_hkt timestamptz, tournament text,
    home text, away text, home_goals integer, away_goals integer,
    outcome text, payout_confirmed boolean, fetched_at timestamptz, raw jsonb
  )
  where j.hkjc_event_id is not null
  on conflict (hkjc_event_id) do update set
    match_id=excluded.match_id,kickoff_hkt=excluded.kickoff_hkt,tournament=excluded.tournament,
    home=excluded.home,away=excluded.away,home_goals=excluded.home_goals,away_goals=excluded.away_goals,
    outcome=excluded.outcome,payout_confirmed=excluded.payout_confirmed,
    fetched_at=excluded.fetched_at,raw=excluded.raw,updated_at=now();

  get diagnostics v_count = row_count;
  return v_count;
end
$$;

revoke all on function public.ft_internal_upsert_results(jsonb) from public, anon, authenticated;
grant execute on function public.ft_internal_upsert_results(jsonb) to service_role;

create or replace function public.ft_internal_import_prediction_archive(payload jsonb)
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
    hkjc_event_id,kickoff_hkt,status,tournament,home_en,away_en,selling,in_play,raw,updated_at
  )
  select distinct
    j.hkjc_event_id,j.kickoff_hkt,'HISTORICAL_PREDICTION',j.league,j.home,j.away,
    false,false,coalesce(j.raw,'{}'::jsonb),now()
  from jsonb_to_recordset(payload) as j(
    hkjc_event_id text,kickoff_hkt timestamptz,captured_at timestamptz,league text,home text,away text,
    forebet_home numeric,forebet_draw numeric,forebet_away numeric,
    hkjc_home numeric,hkjc_draw numeric,hkjc_away numeric,
    bet365_home numeric,bet365_draw numeric,bet365_away numeric,
    dc_home numeric,dc_draw numeric,dc_away numeric,dc_xg_home numeric,dc_xg_away numeric,
    pi_home numeric,pi_draw numeric,pi_away numeric,
    form_home numeric,form_draw numeric,form_away numeric,form_xg_home numeric,form_xg_away numeric,
    model_quality text,form_quality text,raw jsonb
  )
  where j.hkjc_event_id is not null
  on conflict (hkjc_event_id) do nothing;

  with j as (
    select * from jsonb_to_recordset(payload) as x(
      hkjc_event_id text,kickoff_hkt timestamptz,captured_at timestamptz,league text,home text,away text,
      forebet_home numeric,forebet_draw numeric,forebet_away numeric,
      hkjc_home numeric,hkjc_draw numeric,hkjc_away numeric,
      bet365_home numeric,bet365_draw numeric,bet365_away numeric,
      dc_home numeric,dc_draw numeric,dc_away numeric,dc_xg_home numeric,dc_xg_away numeric,
      pi_home numeric,pi_draw numeric,pi_away numeric,
      form_home numeric,form_draw numeric,form_away numeric,form_xg_home numeric,form_xg_away numeric,
      model_quality text,form_quality text,raw jsonb
    )
    where x.hkjc_event_id is not null and x.captured_at < x.kickoff_hkt
  ),
  expanded as (
    select hkjc_event_id,'FOREBET'::text source_key,'1X2'::text market_key,kickoff_hkt,captured_at,
           'LEGACY_ARCHIVE'::text source_status,
           forebet_home/100.0 ph,forebet_draw/100.0 pd,forebet_away/100.0 pa,
           null::numeric xgh,null::numeric xga,hkjc_home oh,hkjc_draw od,hkjc_away oa,raw
    from j where forebet_home is not null and forebet_draw is not null and forebet_away is not null
    union all
    select hkjc_event_id,'HKJC','1X2',kickoff_hkt,captured_at,'MARKET_NOVIG',
           (1/hkjc_home)/((1/hkjc_home)+(1/hkjc_draw)+(1/hkjc_away)),
           (1/hkjc_draw)/((1/hkjc_home)+(1/hkjc_draw)+(1/hkjc_away)),
           (1/hkjc_away)/((1/hkjc_home)+(1/hkjc_draw)+(1/hkjc_away)),
           null,null,hkjc_home,hkjc_draw,hkjc_away,raw
    from j where hkjc_home>1 and hkjc_draw>1 and hkjc_away>1
    union all
    select hkjc_event_id,'BET365','1X2',kickoff_hkt,captured_at,'MARKET_NOVIG',
           (1/bet365_home)/((1/bet365_home)+(1/bet365_draw)+(1/bet365_away)),
           (1/bet365_draw)/((1/bet365_home)+(1/bet365_draw)+(1/bet365_away)),
           (1/bet365_away)/((1/bet365_home)+(1/bet365_draw)+(1/bet365_away)),
           null,null,hkjc_home,hkjc_draw,hkjc_away,raw
    from j where bet365_home>1 and bet365_draw>1 and bet365_away>1
    union all
    select hkjc_event_id,'DC','1X2',kickoff_hkt,captured_at,model_quality,
           dc_home,dc_draw,dc_away,dc_xg_home,dc_xg_away,hkjc_home,hkjc_draw,hkjc_away,raw
    from j where dc_home is not null and dc_draw is not null and dc_away is not null
    union all
    select hkjc_event_id,'PI','1X2',kickoff_hkt,captured_at,model_quality,
           pi_home,pi_draw,pi_away,null,null,hkjc_home,hkjc_draw,hkjc_away,raw
    from j where pi_home is not null and pi_draw is not null and pi_away is not null
    union all
    select hkjc_event_id,'FORM','1X2',kickoff_hkt,captured_at,form_quality,
           form_home,form_draw,form_away,form_xg_home,form_xg_away,hkjc_home,hkjc_draw,hkjc_away,raw
    from j where form_home is not null and form_draw is not null and form_away is not null
  )
  insert into private.prematch_prediction_snapshot (
    hkjc_event_id,source_key,market_key,kickoff_hkt,captured_at,source_status,
    prob_home,prob_draw,prob_away,xg_home,xg_away,
    market_odds_home,market_odds_draw,market_odds_away,raw
  )
  select
    hkjc_event_id,source_key,market_key,kickoff_hkt,captured_at,source_status,
    ph,pd,pa,xgh,xga,oh,od,oa,jsonb_build_object('legacy_prediction_archive',raw)
  from expanded
  on conflict (hkjc_event_id,source_key,market_key) do update set
    kickoff_hkt=excluded.kickoff_hkt,
    captured_at=case
      when excluded.captured_at < excluded.kickoff_hkt
       and excluded.captured_at > private.prematch_prediction_snapshot.captured_at
      then excluded.captured_at else private.prematch_prediction_snapshot.captured_at end,
    source_status=case
      when excluded.captured_at > private.prematch_prediction_snapshot.captured_at
      then excluded.source_status else private.prematch_prediction_snapshot.source_status end,
    prob_home=case when excluded.captured_at > private.prematch_prediction_snapshot.captured_at then excluded.prob_home else private.prematch_prediction_snapshot.prob_home end,
    prob_draw=case when excluded.captured_at > private.prematch_prediction_snapshot.captured_at then excluded.prob_draw else private.prematch_prediction_snapshot.prob_draw end,
    prob_away=case when excluded.captured_at > private.prematch_prediction_snapshot.captured_at then excluded.prob_away else private.prematch_prediction_snapshot.prob_away end,
    xg_home=case when excluded.captured_at > private.prematch_prediction_snapshot.captured_at then excluded.xg_home else private.prematch_prediction_snapshot.xg_home end,
    xg_away=case when excluded.captured_at > private.prematch_prediction_snapshot.captured_at then excluded.xg_away else private.prematch_prediction_snapshot.xg_away end,
    market_odds_home=case when excluded.captured_at > private.prematch_prediction_snapshot.captured_at then excluded.market_odds_home else private.prematch_prediction_snapshot.market_odds_home end,
    market_odds_draw=case when excluded.captured_at > private.prematch_prediction_snapshot.captured_at then excluded.market_odds_draw else private.prematch_prediction_snapshot.market_odds_draw end,
    market_odds_away=case when excluded.captured_at > private.prematch_prediction_snapshot.captured_at then excluded.market_odds_away else private.prematch_prediction_snapshot.market_odds_away end,
    raw=case when excluded.captured_at > private.prematch_prediction_snapshot.captured_at then excluded.raw else private.prematch_prediction_snapshot.raw end;

  get diagnostics v_count = row_count;
  return v_count;
end
$$;

revoke all on function public.ft_internal_import_prediction_archive(jsonb) from public, anon, authenticated;
grant execute on function public.ft_internal_import_prediction_archive(jsonb) to service_role;

create or replace function public.ft_internal_refresh_validation()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
  v_scores integer := 0;
  v_summary integer := 0;
begin
  insert into private.validation_score (
    hkjc_event_id,source_key,market_key,captured_at,outcome,
    rps,brier,logloss,top_pick,top_pick_correct,
    best_edge_selection,best_edge,positive_edge_bet,realized_return,calculated_at,raw
  )
  select
    s.hkjc_event_id,s.source_key,s.market_key,s.captured_at,r.outcome,
    0.5 * (
      power(s.prob_home - case when r.outcome='H' then 1 else 0 end,2)
      + power((s.prob_home+s.prob_draw) - case when r.outcome in ('H','D') then 1 else 0 end,2)
    ),
    (
      power(s.prob_home - case when r.outcome='H' then 1 else 0 end,2)
      + power(s.prob_draw - case when r.outcome='D' then 1 else 0 end,2)
      + power(s.prob_away - case when r.outcome='A' then 1 else 0 end,2)
    ) / 3.0,
    -ln(greatest(1e-12,
      case r.outcome when 'H' then s.prob_home when 'D' then s.prob_draw else s.prob_away end
    )),
    case
      when s.prob_home>=s.prob_draw and s.prob_home>=s.prob_away then 'H'
      when s.prob_draw>=s.prob_away then 'D' else 'A'
    end,
    (case
      when s.prob_home>=s.prob_draw and s.prob_home>=s.prob_away then 'H'
      when s.prob_draw>=s.prob_away then 'D' else 'A'
    end)=r.outcome,
    case
      when coalesce(s.market_odds_home*s.prob_home-1,-999)>=greatest(
        coalesce(s.market_odds_draw*s.prob_draw-1,-999),
        coalesce(s.market_odds_away*s.prob_away-1,-999)
      ) then 'H'
      when coalesce(s.market_odds_draw*s.prob_draw-1,-999)>=coalesce(s.market_odds_away*s.prob_away-1,-999) then 'D'
      else 'A'
    end,
    greatest(
      coalesce(s.market_odds_home*s.prob_home-1,-999),
      coalesce(s.market_odds_draw*s.prob_draw-1,-999),
      coalesce(s.market_odds_away*s.prob_away-1,-999)
    ),
    greatest(
      coalesce(s.market_odds_home*s.prob_home-1,-999),
      coalesce(s.market_odds_draw*s.prob_draw-1,-999),
      coalesce(s.market_odds_away*s.prob_away-1,-999)
    ) > 0,
    case
      when greatest(
        coalesce(s.market_odds_home*s.prob_home-1,-999),
        coalesce(s.market_odds_draw*s.prob_draw-1,-999),
        coalesce(s.market_odds_away*s.prob_away-1,-999)
      ) <= 0 then null
      when (
        case
          when coalesce(s.market_odds_home*s.prob_home-1,-999)>=greatest(
            coalesce(s.market_odds_draw*s.prob_draw-1,-999),
            coalesce(s.market_odds_away*s.prob_away-1,-999)
          ) then 'H'
          when coalesce(s.market_odds_draw*s.prob_draw-1,-999)>=coalesce(s.market_odds_away*s.prob_away-1,-999) then 'D'
          else 'A'
        end
      ) = r.outcome then
        case
          when r.outcome='H' then s.market_odds_home-1
          when r.outcome='D' then s.market_odds_draw-1
          else s.market_odds_away-1
        end
      else -1
    end,
    now(),
    jsonb_build_object('home_goals',r.home_goals,'away_goals',r.away_goals,'source_status',s.source_status)
  from private.prematch_prediction_snapshot s
  join private.match_results r on r.hkjc_event_id=s.hkjc_event_id
  where s.market_key='1X2'
    and s.prob_home is not null and s.prob_draw is not null and s.prob_away is not null
    and r.payout_confirmed is true
  on conflict (hkjc_event_id,source_key,market_key) do update set
    captured_at=excluded.captured_at,outcome=excluded.outcome,
    rps=excluded.rps,brier=excluded.brier,logloss=excluded.logloss,
    top_pick=excluded.top_pick,top_pick_correct=excluded.top_pick_correct,
    best_edge_selection=excluded.best_edge_selection,best_edge=excluded.best_edge,
    positive_edge_bet=excluded.positive_edge_bet,realized_return=excluded.realized_return,
    calculated_at=excluded.calculated_at,raw=excluded.raw;
  get diagnostics v_scores = row_count;

  insert into private.validation_summary (
    source_key,market_key,settled_matches,avg_rps,avg_brier,avg_logloss,
    top_pick_accuracy,positive_edge_bets,positive_edge_roi,validation_state,as_of,raw
  )
  select
    sr.source_key,'1X2',
    count(v.hkjc_event_id)::integer,
    avg(v.rps),avg(v.brier),avg(v.logloss),
    avg(case when v.top_pick_correct then 1.0 else 0.0 end),
    count(*) filter (where v.positive_edge_bet)::integer,
    avg(v.realized_return) filter (where v.positive_edge_bet),
    case when count(v.hkjc_event_id)=0 then 'NO_SAMPLE' else 'HAS_OUT_OF_SAMPLE_DATA' end,
    now(),
    jsonb_build_object('decision_enabled',sr.decision_enabled)
  from private.source_registry sr
  left join private.validation_score v
    on v.source_key=sr.source_key and v.market_key='1X2'
  group by sr.source_key,sr.decision_enabled
  on conflict (source_key,market_key) do update set
    settled_matches=excluded.settled_matches,avg_rps=excluded.avg_rps,avg_brier=excluded.avg_brier,
    avg_logloss=excluded.avg_logloss,top_pick_accuracy=excluded.top_pick_accuracy,
    positive_edge_bets=excluded.positive_edge_bets,positive_edge_roi=excluded.positive_edge_roi,
    validation_state=excluded.validation_state,as_of=excluded.as_of,raw=excluded.raw;
  get diagnostics v_summary = row_count;

  return jsonb_build_object('score_rows',v_scores,'summary_rows',v_summary);
end
$$;

revoke all on function public.ft_internal_refresh_validation() from public, anon, authenticated;
grant execute on function public.ft_internal_refresh_validation() to service_role;

create or replace function public.ft_internal_refresh_phase1_decisions()
returns integer
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
  v_count integer := 0;
begin
  with enabled as (
    select
      e.hkjc_event_id,
      avg(e.prob_home) filter (where e.prob_home is not null) as ph,
      avg(e.prob_draw) filter (where e.prob_draw is not null) as pd,
      avg(e.prob_away) filter (where e.prob_away is not null) as pa,
      count(*) filter (where e.prob_home is not null and e.prob_draw is not null and e.prob_away is not null) as n,
      array_agg(e.source_key order by e.source_key) filter (
        where e.prob_home is not null and e.prob_draw is not null and e.prob_away is not null
      ) as sources
    from private.prediction_evidence_current e
    join private.source_registry sr on sr.source_key=e.source_key
    where sr.decision_enabled is true and e.market_key='1X2'
    group by e.hkjc_event_id
  ),
  active as (
    select
      m.hkjc_event_id,m.kickoff_hkt,
      en.ph,en.pd,en.pa,en.n,en.sources,
      mh.odds oh,md.odds od,ma.odds oa
    from private.matches m
    left join enabled en on en.hkjc_event_id=m.hkjc_event_id
    left join private.market_current mh on mh.hkjc_event_id=m.hkjc_event_id and mh.source_key='HKJC' and mh.market_key='1X2' and mh.selection_key='HOME'
    left join private.market_current md on md.hkjc_event_id=m.hkjc_event_id and md.source_key='HKJC' and md.market_key='1X2' and md.selection_key='DRAW'
    left join private.market_current ma on ma.hkjc_event_id=m.hkjc_event_id and ma.source_key='HKJC' and ma.market_key='1X2' and ma.selection_key='AWAY'
    where m.selling is true and m.kickoff_hkt > now()
  ),
  scored as (
    select *,
      case when n>0 then greatest(oh*ph-1,od*pd-1,oa*pa-1) end as best_edge,
      case when n>0 then
        case when oh*ph-1>=greatest(od*pd-1,oa*pa-1) then 'H'
             when od*pd-1>=oa*pa-1 then 'D' else 'A' end
      end as selection_key,
      case when n>0 then
        case when oh*ph-1>=greatest(od*pd-1,oa*pa-1) then ph
             when od*pd-1>=oa*pa-1 then pd else pa end
      end as model_probability,
      case when n>0 then
        case when oh*ph-1>=greatest(od*pd-1,oa*pa-1) then oh
             when od*pd-1>=oa*pa-1 then od else oa end
      end as market_odds
    from active
  )
  insert into private.phase1_decision_current (
    hkjc_event_id,decision,market_key,selection_key,model_probability,market_odds,
    edge,confidence,reasons,engine_version,calculated_at,raw,updated_at
  )
  select
    hkjc_event_id,
    case
      when coalesce(n,0)=0 then 'CALIBRATION_PENDING'
      when best_edge>0 then 'CANDIDATE_POSITIVE_EV'
      else 'NO_POSITIVE_EV'
    end,
    '1X2',selection_key,model_probability,market_odds,best_edge,null,
    jsonb_build_array(jsonb_build_object(
      'enabled_source_count',coalesce(n,0),
      'enabled_sources',coalesce(to_jsonb(sources),'[]'::jsonb),
      'rule','Only manually decision-enabled sources participate'
    )),
    'phase1_v0_validation_gated',now(),
    jsonb_build_object('ensemble_home',ph,'ensemble_draw',pd,'ensemble_away',pa),
    now()
  from scored
  on conflict (hkjc_event_id) do update set
    decision=excluded.decision,market_key=excluded.market_key,selection_key=excluded.selection_key,
    model_probability=excluded.model_probability,market_odds=excluded.market_odds,
    edge=excluded.edge,confidence=excluded.confidence,reasons=excluded.reasons,
    engine_version=excluded.engine_version,calculated_at=excluded.calculated_at,
    raw=excluded.raw,updated_at=now();
  get diagnostics v_count = row_count;
  return v_count;
end
$$;

revoke all on function public.ft_internal_refresh_phase1_decisions() from public, anon, authenticated;
grant execute on function public.ft_internal_refresh_phase1_decisions() to service_role;

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
    (1/mh.odds) / ((1/mh.odds)+(1/md.odds)+(1/ma.odds))
  end as hkjc_novig_home,
  case when mh.odds > 0 and md.odds > 0 and ma.odds > 0 then
    (1/md.odds) / ((1/mh.odds)+(1/md.odds)+(1/ma.odds))
  end as hkjc_novig_draw,
  case when mh.odds > 0 and md.odds > 0 and ma.odds > 0 then
    (1/ma.odds) / ((1/mh.odds)+(1/md.odds)+(1/ma.odds))
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
  case when mh.odds is not null and ms.prob_home is not null then (mh.odds*ms.prob_home)-1 end as multisource_edge_home,
  case when md.odds is not null and ms.prob_draw is not null then (md.odds*ms.prob_draw)-1 end as multisource_edge_draw,
  case when ma.odds is not null and ms.prob_away is not null then (ma.odds*ms.prob_away)-1 end as multisource_edge_away,
  case when mh.odds is not null and fb.prob_home is not null then (mh.odds*fb.prob_home)-1 end as forebet_edge_home,
  case when md.odds is not null and fb.prob_draw is not null then (md.odds*fb.prob_draw)-1 end as forebet_edge_draw,
  case when ma.odds is not null and fb.prob_away is not null then (ma.odds*fb.prob_away)-1 end as forebet_edge_away,
  greatest(fb.source_updated_at,dc.source_updated_at,pi.source_updated_at,fm.source_updated_at,ms.source_updated_at,m.source_updated_at) as data_updated_at,
  d.decision,
  d.market_key as decision_market,
  d.selection_key as decision_selection,
  d.edge as decision_edge,
  d.engine_version as decision_engine_version,
  d.calculated_at as decision_calculated_at
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
left join private.phase1_decision_current d
  on d.hkjc_event_id=m.hkjc_event_id
where m.selling is true;

revoke all on api.phase1_match_intelligence_v from public, anon, authenticated;
grant select on api.phase1_match_intelligence_v to service_role;
