
create or replace function public.ft_guard_current_time_regression()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  if tg_table_name = 'hkjc_live_odds_current' then
    if old.fetched_at is not null and (new.fetched_at is null or new.fetched_at < old.fetched_at) then return old; end if;
  elsif tg_table_name = 'hkjc_upcoming_current' then
    if old.fetched_at is not null and (new.fetched_at is null or new.fetched_at < old.fetched_at) then return old; end if;
  elsif tg_table_name = 'matches' then
    if old.fetched_at is not null and (new.fetched_at is null or new.fetched_at < old.fetched_at) then return old; end if;
  elsif tg_table_name = 'hkjc_odds_current' then
    if old.fetched_at is not null and (new.fetched_at is null or new.fetched_at < old.fetched_at) then return old; end if;
  elsif tg_table_name = 'live_score_current' then
    if old.updated_at_source is not null and (new.updated_at_source is null or new.updated_at_source < old.updated_at_source) then return old; end if;
  elsif tg_table_name = 'live_stats_current' then
    if old.captured_at_hkt is not null and (new.captured_at_hkt is null or new.captured_at_hkt < old.captured_at_hkt) then return old; end if;
  end if;
  return new;
end;
$$;

create or replace function public.ft_internal_upcoming_canonical_gap_count()
returns integer
language sql
stable
security invoker
set search_path = pg_catalog, public
as $$
  select count(*)::integer
  from public.hkjc_upcoming_current u
  left join public.matches m using (hkjc_event_id)
  where m.hkjc_event_id is null;
$$;

revoke all on function public.ft_internal_upcoming_canonical_gap_count() from public, anon, authenticated;
grant execute on function public.ft_internal_upcoming_canonical_gap_count() to service_role;
