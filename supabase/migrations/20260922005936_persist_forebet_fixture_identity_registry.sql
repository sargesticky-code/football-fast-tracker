
create or replace function public.ft_persist_forebet_availability_registry()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_home_key text;
  v_away_key text;
  v_home_alias_key text;
  v_away_alias_key text;
  v_score numeric;
begin
  if coalesce(new.identity_status,'') <> 'VERIFIED'
     or coalesce(new.fixture_match_score,0) < 0.94
     or nullif(trim(new.source_home_team),'') is null
     or nullif(trim(new.source_away_team),'') is null
     or nullif(trim(new.home_en),'') is null
     or nullif(trim(new.away_en),'') is null then
    return new;
  end if;

  v_score := coalesce(new.fixture_match_score,0);
  v_home_alias_key := public.ft_team_name_key(new.source_home_team);
  v_away_alias_key := public.ft_team_name_key(new.source_away_team);

  select team_key into v_home_key
  from public.team_entities_v2
  where hkjc_name_en=new.home_en
  order by case when status='ACTIVE' then 0 else 1 end, updated_at desc
  limit 1;

  select team_key into v_away_key
  from public.team_entities_v2
  where hkjc_name_en=new.away_en
  order by case when status='ACTIVE' then 0 else 1 end, updated_at desc
  limit 1;

  if v_home_key is not null
     and not exists (
       select 1 from public.team_alias_registry_v2 r
       where r.source='FOREBET'
         and r.alias_key=v_home_alias_key
         and r.team_key<>v_home_key
     ) then
    insert into public.team_alias_registry_v2(
      source,alias_key,team_key,alias,status,confidence,
      evidence_count,distinct_event_count,verification_method,
      first_seen_at,last_seen_at,updated_at
    )
    values(
      'FOREBET',v_home_alias_key,v_home_key,new.source_home_team,'VERIFIED',v_score,
      1,1,'FOREBET_LIVESCORE_VERIFIED_PAIR',
      coalesce(new.checked_at,now()),coalesce(new.checked_at,now()),now()
    )
    on conflict(source,alias_key,team_key) do update
    set alias=excluded.alias,
        status=case
          when public.team_alias_registry_v2.status='AMBIGUOUS' then 'AMBIGUOUS'
          else 'VERIFIED'
        end,
        confidence=case
          when public.team_alias_registry_v2.status='AMBIGUOUS' then 0
          else greatest(coalesce(public.team_alias_registry_v2.confidence,0),excluded.confidence)
        end,
        evidence_count=public.team_alias_registry_v2.evidence_count+1,
        distinct_event_count=greatest(public.team_alias_registry_v2.distinct_event_count,1),
        first_seen_at=least(public.team_alias_registry_v2.first_seen_at,excluded.first_seen_at),
        last_seen_at=greatest(public.team_alias_registry_v2.last_seen_at,excluded.last_seen_at),
        verification_method=case
          when public.team_alias_registry_v2.status='AMBIGUOUS'
            then public.team_alias_registry_v2.verification_method
          else 'FOREBET_LIVESCORE_VERIFIED_PAIR'
        end,
        updated_at=now();
  end if;

  if v_away_key is not null
     and not exists (
       select 1 from public.team_alias_registry_v2 r
       where r.source='FOREBET'
         and r.alias_key=v_away_alias_key
         and r.team_key<>v_away_key
     ) then
    insert into public.team_alias_registry_v2(
      source,alias_key,team_key,alias,status,confidence,
      evidence_count,distinct_event_count,verification_method,
      first_seen_at,last_seen_at,updated_at
    )
    values(
      'FOREBET',v_away_alias_key,v_away_key,new.source_away_team,'VERIFIED',v_score,
      1,1,'FOREBET_LIVESCORE_VERIFIED_PAIR',
      coalesce(new.checked_at,now()),coalesce(new.checked_at,now()),now()
    )
    on conflict(source,alias_key,team_key) do update
    set alias=excluded.alias,
        status=case
          when public.team_alias_registry_v2.status='AMBIGUOUS' then 'AMBIGUOUS'
          else 'VERIFIED'
        end,
        confidence=case
          when public.team_alias_registry_v2.status='AMBIGUOUS' then 0
          else greatest(coalesce(public.team_alias_registry_v2.confidence,0),excluded.confidence)
        end,
        evidence_count=public.team_alias_registry_v2.evidence_count+1,
        distinct_event_count=greatest(public.team_alias_registry_v2.distinct_event_count,1),
        first_seen_at=least(public.team_alias_registry_v2.first_seen_at,excluded.first_seen_at),
        last_seen_at=greatest(public.team_alias_registry_v2.last_seen_at,excluded.last_seen_at),
        verification_method=case
          when public.team_alias_registry_v2.status='AMBIGUOUS'
            then public.team_alias_registry_v2.verification_method
          else 'FOREBET_LIVESCORE_VERIFIED_PAIR'
        end,
        updated_at=now();
  end if;

  return new;
end
$$;

drop trigger if exists trg_forebet_availability_registry_persist
  on public.forebet_availability;

create trigger trg_forebet_availability_registry_persist
after insert or update of
  source_home_team,source_away_team,fixture_match_score,identity_status
on public.forebet_availability
for each row
execute function public.ft_persist_forebet_availability_registry();

revoke all on function public.ft_persist_forebet_availability_registry() from public;
revoke all on function public.ft_persist_forebet_availability_registry() from anon;
revoke all on function public.ft_persist_forebet_availability_registry() from authenticated;
