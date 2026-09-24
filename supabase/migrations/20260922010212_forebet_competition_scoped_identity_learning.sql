
create or replace function public.ft_learn_forebet_availability_context()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_home_key text;
  v_away_key text;
  v_home_zh text;
  v_away_zh text;
  v_comp_key text;
  v_seen timestamptz;
begin
  if coalesce(new.identity_status,'') <> 'CONTEXT_VERIFIED'
     or coalesce(new.fixture_match_score,0) < 0.94
     or nullif(trim(new.source_home_team),'') is null
     or nullif(trim(new.source_away_team),'') is null
     or nullif(trim(new.source_competition),'') is null
     or nullif(trim(new.league_zh),'') is null
     or nullif(trim(new.home_en),'') is null
     or nullif(trim(new.away_en),'') is null then
    return new;
  end if;

  v_seen := coalesce(new.checked_at,now());
  v_comp_key := public.ft_team_name_key(new.source_competition);

  select team_key,hkjc_name_zh into v_home_key,v_home_zh
  from public.team_entities_v2
  where hkjc_name_en=new.home_en
  order by case when status='ACTIVE' then 0 else 1 end, updated_at desc
  limit 1;

  select team_key,hkjc_name_zh into v_away_key,v_away_zh
  from public.team_entities_v2
  where hkjc_name_en=new.away_en
  order by case when status='ACTIVE' then 0 else 1 end, updated_at desc
  limit 1;

  if v_home_key is null or v_away_key is null then
    return new;
  end if;

  insert into public.competition_name_master(
    source,source_competition,source_key,canonical_tournament,status,confidence,
    event_count,first_seen_at,last_seen_at,evidence_sources,updated_at
  )
  values(
    'FOREBET',new.source_competition,v_comp_key,new.league_zh,'VERIFIED',
    new.fixture_match_score,1,v_seen,v_seen,
    '["FOREBET_LIVESCORE_CONTEXT"]'::jsonb,now()
  )
  on conflict(source,source_key,canonical_tournament) do update
  set source_competition=excluded.source_competition,
      status='VERIFIED',
      confidence=greatest(public.competition_name_master.confidence,excluded.confidence),
      event_count=public.competition_name_master.event_count+1,
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

  insert into public.team_name_context_master(
    source,source_name,source_key,source_competition,competition_key,
    canonical_tournament,team_key,hkjc_name_en,hkjc_name_zh,status,confidence,
    event_count,first_seen_at,last_seen_at,evidence_sources,updated_at
  )
  values
    ('FOREBET',new.source_home_team,public.ft_team_name_key(new.source_home_team),
     new.source_competition,v_comp_key,new.league_zh,v_home_key,new.home_en,v_home_zh,
     'VERIFIED',new.fixture_match_score,1,v_seen,v_seen,
     '["FOREBET_LIVESCORE_CONTEXT"]'::jsonb,now()),
    ('FOREBET',new.source_away_team,public.ft_team_name_key(new.source_away_team),
     new.source_competition,v_comp_key,new.league_zh,v_away_key,new.away_en,v_away_zh,
     'VERIFIED',new.fixture_match_score,1,v_seen,v_seen,
     '["FOREBET_LIVESCORE_CONTEXT"]'::jsonb,now())
  on conflict(source,source_key,competition_key,canonical_tournament,team_key) do update
  set source_name=excluded.source_name,
      source_competition=excluded.source_competition,
      hkjc_name_en=excluded.hkjc_name_en,
      hkjc_name_zh=excluded.hkjc_name_zh,
      status='VERIFIED',
      confidence=greatest(public.team_name_context_master.confidence,excluded.confidence),
      event_count=public.team_name_context_master.event_count+1,
      first_seen_at=least(public.team_name_context_master.first_seen_at,excluded.first_seen_at),
      last_seen_at=greatest(public.team_name_context_master.last_seen_at,excluded.last_seen_at),
      evidence_sources=(
        select coalesce(jsonb_agg(distinct x),'[]'::jsonb)
        from jsonb_array_elements(
          coalesce(public.team_name_context_master.evidence_sources,'[]'::jsonb)
          || excluded.evidence_sources
        ) x
      ),
      updated_at=now();

  return new;
end
$$;

drop trigger if exists trg_forebet_availability_context_learn
  on public.forebet_availability;

create trigger trg_forebet_availability_context_learn
after insert or update of
  source_home_team,source_away_team,source_competition,
  fixture_match_score,identity_status,identity_source
on public.forebet_availability
for each row
execute function public.ft_learn_forebet_availability_context();

revoke all on function public.ft_learn_forebet_availability_context() from public;
revoke all on function public.ft_learn_forebet_availability_context() from anon;
revoke all on function public.ft_learn_forebet_availability_context() from authenticated;
