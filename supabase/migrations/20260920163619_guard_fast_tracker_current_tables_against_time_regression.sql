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

drop trigger if exists trg_guard_hkjc_live_odds_time on public.hkjc_live_odds_current;
create trigger trg_guard_hkjc_live_odds_time
before update on public.hkjc_live_odds_current
for each row execute function public.ft_guard_current_time_regression();

drop trigger if exists trg_guard_hkjc_upcoming_time on public.hkjc_upcoming_current;
create trigger trg_guard_hkjc_upcoming_time
before update on public.hkjc_upcoming_current
for each row execute function public.ft_guard_current_time_regression();

drop trigger if exists trg_guard_live_score_time on public.live_score_current;
create trigger trg_guard_live_score_time
before update on public.live_score_current
for each row execute function public.ft_guard_current_time_regression();

drop trigger if exists trg_guard_live_stats_time on public.live_stats_current;
create trigger trg_guard_live_stats_time
before update on public.live_stats_current
for each row execute function public.ft_guard_current_time_regression();
