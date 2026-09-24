create table if not exists public.team_name_master (
    source text not null,
    source_name text not null,
    source_key text not null,
    team_key text not null references public.team_entities_v2(team_key),
    hkjc_name_en text not null,
    hkjc_name_zh text,
    status text not null check (status in ('VERIFIED','CANDIDATE','AMBIGUOUS')),
    confidence numeric,
    event_count integer not null default 0,
    first_seen_at timestamptz,
    last_seen_at timestamptz,
    evidence_sources jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now(),
    primary key(source,source_key,team_key)
  );

create index if not exists team_name_master_lookup_idx
  on public.team_name_master(source,source_key,status);

alter table public.team_name_master enable row level security;

create or replace view public.team_name_lookup as
with verified as (
  select
    m.*,
    count(*) filter(where m.status='VERIFIED')
      over(partition by m.source,m.source_key) as verified_targets
  from public.team_name_master m
)
select
  source,source_name,source_key,team_key,hkjc_name_en,hkjc_name_zh,
  confidence,event_count,last_seen_at
from verified
where status='VERIFIED'
  and verified_targets=1;

create or replace function public.ft_resolve_team_name(p_source text,p_name text)
returns table(
  team_key text,
  hkjc_name_en text,
  hkjc_name_zh text,
  confidence numeric
)
language sql
stable
security definer
set search_path=public
as $$
  select l.team_key,l.hkjc_name_en,l.hkjc_name_zh,l.confidence
  from public.team_name_lookup l
  where l.source=upper(trim(p_source))
    and l.source_key=public.ft_team_name_key(p_name)
  limit 1
$$;

create or replace function public.ft_refresh_team_name_master()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_total integer := 0;
  v_verified integer := 0;
  v_candidate integer := 0;
  v_ambiguous integer := 0;
begin
  truncate table public.team_name_master;

  with canonical_events as (
    select
      m.hkjc_event_id,
      coalesce(u.home_en,m.home_en) home_en,
      coalesce(u.away_en,m.away_en) away_en,
      coalesce(u.home_zh,m.home_zh) home_zh,
      coalesce(u.away_zh,m.away_zh) away_zh,
      coalesce(u.kickoff_hkt,m.kickoff_hkt) kickoff_hkt
    from public.matches m
    left join public.hkjc_upcoming_current u using(hkjc_event_id)
    union
    select
      u.hkjc_event_id,u.home_en,u.away_en,u.home_zh,u.away_zh,u.kickoff_hkt
    from public.hkjc_upcoming_current u
    where not exists (
      select 1 from public.matches m where m.hkjc_event_id=u.hkjc_event_id
    )
  ),
  obs as (
    select
      'HKJC_EN'::text source,
      te.hkjc_name_en source_name,
      te.name_key source_key,
      te.team_key,
      null::text event_id,
      1.0::numeric confidence,
      coalesce(te.last_seen_at,now()) observed_at,
      'CANONICAL'::text evidence_kind
    from public.team_entities_v2 te

    union all
    select
      'HKJC_ZH',
      te.hkjc_name_zh,
      public.ft_team_name_key(te.hkjc_name_zh),
      te.team_key,
      null,
      1.0,
      coalesce(te.last_seen_at,now()),
      'CANONICAL'
    from public.team_entities_v2 te
    where nullif(trim(te.hkjc_name_zh),'') is not null

    union all
    select
      'FOREBET',
      trim(fp.forebet_home_team),
      public.ft_team_name_key(fp.forebet_home_team),
      'HKJC:'||public.ft_team_name_key(ce.home_en),
      fp.hkjc_event_id,
      0.93,
      coalesce(fp.fetched_at,now()),
      'EVENT_LINK'
    from public.forebet_predictions fp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.home_en)
    where nullif(trim(fp.forebet_home_team),'') is not null

    union all
    select
      'FOREBET',
      trim(fp.forebet_away_team),
      public.ft_team_name_key(fp.forebet_away_team),
      'HKJC:'||public.ft_team_name_key(ce.away_en),
      fp.hkjc_event_id,
      0.93,
      coalesce(fp.fetched_at,now()),
      'EVENT_LINK'
    from public.forebet_predictions fp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.away_en)
    where nullif(trim(fp.forebet_away_team),'') is not null

    union all
    select
      'FOOTBALL_DATA',
      trim(mp.model_home_name),
      public.ft_team_name_key(mp.model_home_name),
      'HKJC:'||public.ft_team_name_key(ce.home_en),
      mp.hkjc_event_id,
      coalesce(mp.team_match_quality,0.0),
      coalesce(mp.fetched_at,mp.updated_at,now()),
      'MODEL_EVENT_LINK'
    from public.model_predictions mp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.home_en)
    where mp.model_source ilike '%football-data.co.uk%'
      and nullif(trim(mp.model_home_name),'') is not null

    union all
    select
      'FOOTBALL_DATA',
      trim(mp.model_away_name),
      public.ft_team_name_key(mp.model_away_name),
      'HKJC:'||public.ft_team_name_key(ce.away_en),
      mp.hkjc_event_id,
      coalesce(mp.team_match_quality,0.0),
      coalesce(mp.fetched_at,mp.updated_at,now()),
      'MODEL_EVENT_LINK'
    from public.model_predictions mp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.away_en)
    where mp.model_source ilike '%football-data.co.uk%'
      and nullif(trim(mp.model_away_name),'') is not null

    union all
    select
      'INTERNAL_MODEL',
      trim(mp.model_home_name),
      public.ft_team_name_key(mp.model_home_name),
      'HKJC:'||public.ft_team_name_key(ce.home_en),
      mp.hkjc_event_id,
      coalesce(mp.team_match_quality,0.0),
      coalesce(mp.fetched_at,mp.updated_at,now()),
      'MODEL_EVENT_LINK'
    from public.model_predictions mp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.home_en)
    where mp.model_source not ilike '%football-data.co.uk%'
      and nullif(trim(mp.model_home_name),'') is not null

    union all
    select
      'INTERNAL_MODEL',
      trim(mp.model_away_name),
      public.ft_team_name_key(mp.model_away_name),
      'HKJC:'||public.ft_team_name_key(ce.away_en),
      mp.hkjc_event_id,
      coalesce(mp.team_match_quality,0.0),
      coalesce(mp.fetched_at,mp.updated_at,now()),
      'MODEL_EVENT_LINK'
    from public.model_predictions mp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.away_en)
    where mp.model_source not ilike '%football-data.co.uk%'
      and nullif(trim(mp.model_away_name),'') is not null

    union all
    select
      'OPTA',
      trim(hp.home_opta_name),
      public.ft_team_name_key(hp.home_opta_name),
      'HKJC:'||public.ft_team_name_key(ce.home_en),
      hp.hkjc_event_id,
      coalesce(hp.home_match_confidence,0.0),
      coalesce(hp.fetched_at,hp.updated_at,now()),
      'POWER_EVENT_LINK'
    from public.hkjc_power_current hp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.home_en)
    where nullif(trim(hp.home_opta_name),'') is not null

    union all
    select
      'OPTA',
      trim(hp.away_opta_name),
      public.ft_team_name_key(hp.away_opta_name),
      'HKJC:'||public.ft_team_name_key(ce.away_en),
      hp.hkjc_event_id,
      coalesce(hp.away_match_confidence,0.0),
      coalesce(hp.fetched_at,hp.updated_at,now()),
      'POWER_EVENT_LINK'
    from public.hkjc_power_current hp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.away_en)
    where nullif(trim(hp.away_opta_name),'') is not null

    union all
    select
      'FORM',
      trim(fp.home),
      public.ft_team_name_key(fp.home),
      'HKJC:'||public.ft_team_name_key(ce.home_en),
      fp.hkjc_event_id,
      case when fp.quality='FORM_MODELED' then 0.98 else 0.92 end,
      coalesce(fp.fetched_at,fp.updated_at,now()),
      'FORM_EVENT_LINK'
    from public.form_predictions fp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.home_en)
    where nullif(trim(fp.home),'') is not null

    union all
    select
      'FORM',
      trim(fp.away),
      public.ft_team_name_key(fp.away),
      'HKJC:'||public.ft_team_name_key(ce.away_en),
      fp.hkjc_event_id,
      case when fp.quality='FORM_MODELED' then 0.98 else 0.92 end,
      coalesce(fp.fetched_at,fp.updated_at,now()),
      'FORM_EVENT_LINK'
    from public.form_predictions fp
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.away_en)
    where nullif(trim(fp.away),'') is not null

    union all
    select
      upper(coalesce(nullif(trim(pf.source),''),'FALLBACK')),
      trim(pf.home_en),
      public.ft_team_name_key(pf.home_en),
      'HKJC:'||public.ft_team_name_key(ce.home_en),
      pf.hkjc_event_id,
      coalesce(pf.match_score,0.0),
      coalesce(pf.fetched_at,pf.updated_at,now()),
      'FALLBACK_EVENT_LINK'
    from public.prediction_fallback_current pf
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.home_en)
    where nullif(trim(pf.home_en),'') is not null

    union all
    select
      upper(coalesce(nullif(trim(pf.source),''),'FALLBACK')),
      trim(pf.away_en),
      public.ft_team_name_key(pf.away_en),
      'HKJC:'||public.ft_team_name_key(ce.away_en),
      pf.hkjc_event_id,
      coalesce(pf.match_score,0.0),
      coalesce(pf.fetched_at,pf.updated_at,now()),
      'FALLBACK_EVENT_LINK'
    from public.prediction_fallback_current pf
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.away_en)
    where nullif(trim(pf.away_en),'') is not null

    union all
    select
      upper(coalesce(nullif(trim(ls.source),''),'LIVE_PROVIDER')),
      trim(ls.source_home),
      public.ft_team_name_key(ls.source_home),
      'HKJC:'||public.ft_team_name_key(ce.home_en),
      ls.hkjc_event_id,
      coalesce(ls.match_confidence,0.0),
      coalesce(ls.source_updated_at,ls.updated_at_source,now()),
      'LIVE_EVENT_LINK'
    from public.live_score_current ls
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.home_en)
    where nullif(trim(ls.source_home),'') is not null

    union all
    select
      upper(coalesce(nullif(trim(ls.source),''),'LIVE_PROVIDER')),
      trim(ls.source_away),
      public.ft_team_name_key(ls.source_away),
      'HKJC:'||public.ft_team_name_key(ce.away_en),
      ls.hkjc_event_id,
      coalesce(ls.match_confidence,0.0),
      coalesce(ls.source_updated_at,ls.updated_at_source,now()),
      'LIVE_EVENT_LINK'
    from public.live_score_current ls
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.away_en)
    where nullif(trim(ls.source_away),'') is not null

    union all
    select
      'BET365',
      trim(b.home),
      public.ft_team_name_key(b.home),
      'HKJC:'||public.ft_team_name_key(ce.home_en),
      b.hkjc_event_id,
      coalesce(b.match_quality,0.0),
      coalesce(b.fetched_at,b.updated_at,now()),
      'BET365_EVENT_LINK'
    from public.bet365_current b
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.home_en)
    where nullif(trim(b.home),'') is not null

    union all
    select
      'BET365',
      trim(b.away),
      public.ft_team_name_key(b.away),
      'HKJC:'||public.ft_team_name_key(ce.away_en),
      b.hkjc_event_id,
      coalesce(b.match_quality,0.0),
      coalesce(b.fetched_at,b.updated_at,now()),
      'BET365_EVENT_LINK'
    from public.bet365_current b
    join canonical_events ce using(hkjc_event_id)
    join public.team_entities_v2 te
      on te.team_key='HKJC:'||public.ft_team_name_key(ce.away_en)
    where nullif(trim(b.away),'') is not null
  ),
  usable as (
    select *
    from obs
    where source_key is not null
      and team_key is not null
  ),
  grouped as (
    select
      source,source_key,team_key,
      (array_agg(source_name order by observed_at desc))[1] source_name,
      count(distinct event_id) filter(where event_id is not null) event_count,
      min(observed_at) first_seen_at,
      max(observed_at) last_seen_at,
      max(confidence) confidence,
      jsonb_agg(distinct evidence_kind) evidence_sources
    from usable
    group by source,source_key,team_key
  ),
  collisions as (
    select source,source_key,count(*) target_count
    from grouped
    group by source,source_key
  )
  insert into public.team_name_master(
    source,source_name,source_key,team_key,hkjc_name_en,hkjc_name_zh,
    status,confidence,event_count,first_seen_at,last_seen_at,evidence_sources,updated_at
  )
  select
    g.source,g.source_name,g.source_key,g.team_key,
    te.hkjc_name_en,te.hkjc_name_zh,
    case
      when c.target_count>1 then 'AMBIGUOUS'
      when g.source in ('HKJC_EN','HKJC_ZH') then 'VERIFIED'
      when g.confidence>=0.93 then 'VERIFIED'
      when g.event_count>=2 then 'VERIFIED'
      when g.source_key=te.name_key then 'VERIFIED'
      else 'CANDIDATE'
    end,
    case when c.target_count>1 then 0 else g.confidence end,
    g.event_count,g.first_seen_at,g.last_seen_at,g.evidence_sources,now()
  from grouped g
  join collisions c using(source,source_key)
  join public.team_entities_v2 te using(team_key);

  select count(*) into v_total from public.team_name_master;
  select count(*) into v_verified from public.team_name_master where status='VERIFIED';
  select count(*) into v_candidate from public.team_name_master where status='CANDIDATE';
  select count(*) into v_ambiguous from public.team_name_master where status='AMBIGUOUS';

  insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
  values(
    'TEAM_NAME_MASTER','registry',v_verified::text,
    case when v_ambiguous>0 then 'WARN' else 'OK' end,
    'Universal source-team-name registry. Importers should resolve here before any fuzzy matching.',
    now(),
    jsonb_build_object(
      'total_rows',v_total,
      'verified_rows',v_verified,
      'candidate_rows',v_candidate,
      'ambiguous_rows',v_ambiguous
    )
  )
  on conflict(source,metric) do update set
    value_text=excluded.value_text,
    status=excluded.status,
    notes=excluded.notes,
    observed_at=excluded.observed_at,
    raw=excluded.raw;

  return jsonb_build_object(
    'total_rows',v_total,
    'verified_rows',v_verified,
    'candidate_rows',v_candidate,
    'ambiguous_rows',v_ambiguous
  );
end
$$;

create or replace function public.ft_alias_maintenance_v2()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_refresh jsonb;
  v_promote jsonb;
  v_master jsonb;
begin
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  return jsonb_build_object(
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master
  );
end
$$;
