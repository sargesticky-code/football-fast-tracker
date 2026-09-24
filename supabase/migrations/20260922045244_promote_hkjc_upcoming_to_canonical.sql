
create or replace function public.ft_promote_hkjc_upcoming_to_canonical()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
begin
  insert into public.matches (
    hkjc_event_id,hkjc_match_id,kickoff_hkt,status,tournament,
    home_en,away_en,home_zh,away_zh,pools,pool_status,in_play,selling,
    fetched_at,source_updated_at,raw,updated_at
  )
  values (
    new.hkjc_event_id,new.match_id,new.kickoff_hkt,new.status,new.tournament,
    new.home_en,new.away_en,new.home_zh,new.away_zh,null,new.pool_status,false,new.selling,
    new.fetched_at,coalesce(new.odds_updated_at,new.fetched_at),new.raw,now()
  )
  on conflict (hkjc_event_id) do update set
    hkjc_match_id = excluded.hkjc_match_id,
    kickoff_hkt = excluded.kickoff_hkt,
    status = excluded.status,
    tournament = excluded.tournament,
    home_en = excluded.home_en,
    away_en = excluded.away_en,
    home_zh = excluded.home_zh,
    away_zh = excluded.away_zh,
    pool_status = excluded.pool_status,
    selling = excluded.selling,
    fetched_at = excluded.fetched_at,
    source_updated_at = excluded.source_updated_at,
    raw = excluded.raw,
    updated_at = now()
  where public.matches.fetched_at is null
     or excluded.fetched_at >= public.matches.fetched_at;

  insert into public.hkjc_odds_current (
    hkjc_event_id,had_home,had_draw,had_away,
    hil_line,hil_over,hil_under,
    chl_line,chl_over,chl_under,
    fetched_at,odds_updated_at,raw,updated_at
  )
  values (
    new.hkjc_event_id,new.had_home,new.had_draw,new.had_away,
    new.hil_line,new.hil_over,new.hil_under,
    new.chl_line,new.chl_over,new.chl_under,
    new.fetched_at,new.odds_updated_at,new.raw,now()
  )
  on conflict (hkjc_event_id) do update set
    had_home = excluded.had_home,
    had_draw = excluded.had_draw,
    had_away = excluded.had_away,
    hil_line = excluded.hil_line,
    hil_over = excluded.hil_over,
    hil_under = excluded.hil_under,
    chl_line = excluded.chl_line,
    chl_over = excluded.chl_over,
    chl_under = excluded.chl_under,
    fetched_at = excluded.fetched_at,
    odds_updated_at = excluded.odds_updated_at,
    raw = excluded.raw,
    updated_at = now()
  where public.hkjc_odds_current.fetched_at is null
     or excluded.fetched_at >= public.hkjc_odds_current.fetched_at;

  return new;
end;
$$;

drop trigger if exists trg_promote_hkjc_upcoming_to_canonical on public.hkjc_upcoming_current;
create trigger trg_promote_hkjc_upcoming_to_canonical
after insert or update on public.hkjc_upcoming_current
for each row
execute function public.ft_promote_hkjc_upcoming_to_canonical();

create or replace function public.ft_guard_current_time_regression()
returns trigger
language plpgsql
as $$
begin
  if tg_table_name = 'hkjc_live_odds_current' then
    if old.fetched_at is not null and (new.fetched_at is null or new.fetched_at < old.fetched_at) then
      return old;
    end if;
  elsif tg_table_name = 'hkjc_upcoming_current' then
    if old.fetched_at is not null and (new.fetched_at is null or new.fetched_at < old.fetched_at) then
      return old;
    end if;
  elsif tg_table_name = 'matches' then
    if old.fetched_at is not null and (new.fetched_at is null or new.fetched_at < old.fetched_at) then
      return old;
    end if;
  elsif tg_table_name = 'hkjc_odds_current' then
    if old.fetched_at is not null and (new.fetched_at is null or new.fetched_at < old.fetched_at) then
      return old;
    end if;
  elsif tg_table_name = 'live_score_current' then
    if old.updated_at_source is not null and (new.updated_at_source is null or new.updated_at_source < old.updated_at_source) then
      return old;
    end if;
  elsif tg_table_name = 'live_stats_current' then
    if old.captured_at_hkt is not null and (new.captured_at_hkt is null or new.captured_at_hkt < old.captured_at_hkt) then
      return old;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_guard_matches_time on public.matches;
create trigger trg_guard_matches_time
before update on public.matches
for each row execute function public.ft_guard_current_time_regression();

drop trigger if exists trg_guard_hkjc_odds_time on public.hkjc_odds_current;
create trigger trg_guard_hkjc_odds_time
before update on public.hkjc_odds_current
for each row execute function public.ft_guard_current_time_regression();

create or replace function public.ft_refresh_after_hkjc_upcoming_stmt()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
begin
  perform public.ft_internal_refresh_phase1_core();
  perform public.ft_refresh_phase1_coverage_guard();
  return null;
end;
$$;

drop trigger if exists trg_refresh_after_hkjc_upcoming_stmt on public.hkjc_upcoming_current;
create trigger trg_refresh_after_hkjc_upcoming_stmt
after insert or update on public.hkjc_upcoming_current
for each statement
execute function public.ft_refresh_after_hkjc_upcoming_stmt();

create or replace function public.ft_internal_upcoming_canonical_gap_count()
returns integer
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
  select count(*)::integer
  from public.hkjc_upcoming_current u
  left join public.matches m using (hkjc_event_id)
  where m.hkjc_event_id is null;
$$;

insert into public.matches (
  hkjc_event_id,hkjc_match_id,kickoff_hkt,status,tournament,
  home_en,away_en,home_zh,away_zh,pools,pool_status,in_play,selling,
  fetched_at,source_updated_at,raw,updated_at
)
select
  u.hkjc_event_id,u.match_id,u.kickoff_hkt,u.status,u.tournament,
  u.home_en,u.away_en,u.home_zh,u.away_zh,null,u.pool_status,false,u.selling,
  u.fetched_at,coalesce(u.odds_updated_at,u.fetched_at),u.raw,now()
from public.hkjc_upcoming_current u
on conflict (hkjc_event_id) do update set
  hkjc_match_id=excluded.hkjc_match_id,
  kickoff_hkt=excluded.kickoff_hkt,
  status=excluded.status,
  tournament=excluded.tournament,
  home_en=excluded.home_en,
  away_en=excluded.away_en,
  home_zh=excluded.home_zh,
  away_zh=excluded.away_zh,
  pool_status=excluded.pool_status,
  selling=excluded.selling,
  fetched_at=excluded.fetched_at,
  source_updated_at=excluded.source_updated_at,
  raw=excluded.raw,
  updated_at=now()
where public.matches.fetched_at is null
   or excluded.fetched_at >= public.matches.fetched_at;

insert into public.hkjc_odds_current (
  hkjc_event_id,had_home,had_draw,had_away,
  hil_line,hil_over,hil_under,
  chl_line,chl_over,chl_under,
  fetched_at,odds_updated_at,raw,updated_at
)
select
  u.hkjc_event_id,u.had_home,u.had_draw,u.had_away,
  u.hil_line,u.hil_over,u.hil_under,
  u.chl_line,u.chl_over,u.chl_under,
  u.fetched_at,u.odds_updated_at,u.raw,now()
from public.hkjc_upcoming_current u
on conflict (hkjc_event_id) do update set
  had_home=excluded.had_home,
  had_draw=excluded.had_draw,
  had_away=excluded.had_away,
  hil_line=excluded.hil_line,
  hil_over=excluded.hil_over,
  hil_under=excluded.hil_under,
  chl_line=excluded.chl_line,
  chl_over=excluded.chl_over,
  chl_under=excluded.chl_under,
  fetched_at=excluded.fetched_at,
  odds_updated_at=excluded.odds_updated_at,
  raw=excluded.raw,
  updated_at=now()
where public.hkjc_odds_current.fetched_at is null
   or excluded.fetched_at >= public.hkjc_odds_current.fetched_at;

select public.ft_internal_refresh_phase1_core();
select public.ft_refresh_phase1_coverage_guard();
