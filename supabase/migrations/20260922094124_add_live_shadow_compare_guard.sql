
create or replace view public.live_shadow_compare_v
with (security_invoker=true)
as
select
  l.hkjc_event_id,
  l.fetched_at as hkjc_live_at,
  s.updated_at_source as production_score_at,
  sh.captured_at as shadow_at,
  s.source as production_source,
  s.source_match_id as production_source_match_id,
  sh.source as shadow_source,
  sh.source_match_id as shadow_source_match_id,
  s.home_score as production_home_score,
  s.away_score as production_away_score,
  sh.home_score as shadow_home_score,
  sh.away_score as shadow_away_score,
  s.minute as production_minute,
  sh.minute as shadow_minute,
  d.detail_status as shadow_detail_status,
  case
    when sh.hkjc_event_id is null then false
    else true
  end as shadow_present,
  case
    when s.source_match_id is null or sh.source_match_id is null then null
    else s.source_match_id=sh.source_match_id
  end as source_id_match,
  case
    when s.home_score is null or s.away_score is null or sh.home_score is null or sh.away_score is null then null
    else s.home_score=sh.home_score and s.away_score=sh.away_score
  end as score_match,
  case
    when s.minute is null or sh.minute is null then null
    else abs(s.minute-sh.minute)
  end as minute_delta
from public.hkjc_live_odds_current l
left join public.live_score_current s using(hkjc_event_id)
left join public.live_source_shadow_current sh using(hkjc_event_id)
left join public.live_detail_shadow_current d using(hkjc_event_id)
where l.fetched_at>=now()-interval '3 minutes';

revoke all on public.live_shadow_compare_v from anon,authenticated;
grant select on public.live_shadow_compare_v to service_role;

create or replace function public.ft_refresh_live_shadow_compare_guard()
returns jsonb
language plpgsql
security definer
set search_path=pg_catalog,public
as $$
declare
  v_live integer:=0;
  v_shadow integer:=0;
  v_score_comp integer:=0;
  v_score_agree integer:=0;
  v_id_comp integer:=0;
  v_id_agree integer:=0;
  v_minute_bad integer:=0;
  v_detail_ok integer:=0;
  v_status text:='OK';
  v_notes text:='';
  v_rows jsonb:='[]'::jsonb;
begin
  select
    count(*)::int,
    count(*) filter(where shadow_present)::int,
    count(*) filter(where score_match is not null)::int,
    count(*) filter(where score_match is true)::int,
    count(*) filter(where source_id_match is not null)::int,
    count(*) filter(where source_id_match is true)::int,
    count(*) filter(where minute_delta is not null and minute_delta>2)::int,
    count(*) filter(where shadow_detail_status in ('CAPTURED','CAPTURED_SOFASCORE_FALLBACK'))::int,
    coalesce(jsonb_agg(to_jsonb(c)),'[]'::jsonb)
  into
    v_live,v_shadow,v_score_comp,v_score_agree,v_id_comp,v_id_agree,
    v_minute_bad,v_detail_ok,v_rows
  from public.live_shadow_compare_v c;

  if v_live=0 then
    v_status:='OK';
    v_notes:='No fresh live matches; shadow compare idle.';
  elsif v_shadow<v_live then
    v_status:='WARN';
    v_notes:=format('Native shadow coverage %s/%s live matches.',v_shadow,v_live);
  elsif v_score_comp>0 and v_score_agree<v_score_comp then
    v_status:='WARN';
    v_notes:=format('Native shadow score agreement %s/%s.',v_score_agree,v_score_comp);
  elsif v_minute_bad>0 then
    v_status:='WARN';
    v_notes:=format('Native shadow minute drift >2 on %s live matches.',v_minute_bad);
  elsif v_id_comp>0 and v_id_agree<v_id_comp then
    v_status:='WARN';
    v_notes:=format('Native shadow source-id agreement %s/%s.',v_id_agree,v_id_comp);
  else
    v_status:='OK';
    v_notes:=format('Native shadow aligned: coverage %s/%s, scores %s/%s, ids %s/%s, detail %s.',
      v_shadow,v_live,v_score_agree,v_score_comp,v_id_agree,v_id_comp,v_detail_ok);
  end if;

  insert into public.source_health(source,metric,status,value_text,notes,observed_at,raw)
  values(
    'LIVE_SHADOW_COMPARE','heartbeat',v_status,
    concat('coverage=',v_shadow,'/',v_live,' score=',v_score_agree,'/',v_score_comp,' id=',v_id_agree,'/',v_id_comp,' detail=',v_detail_ok),
    v_notes,now(),
    jsonb_build_object(
      'live',v_live,'shadow',v_shadow,
      'score_comparable',v_score_comp,'score_agree',v_score_agree,
      'id_comparable',v_id_comp,'id_agree',v_id_agree,
      'minute_bad',v_minute_bad,'detail_ok',v_detail_ok,
      'matches',v_rows
    )
  )
  on conflict(source,metric) do update set
    status=excluded.status,value_text=excluded.value_text,notes=excluded.notes,
    observed_at=excluded.observed_at,raw=excluded.raw;

  return jsonb_build_object(
    'status',v_status,'live',v_live,'shadow',v_shadow,
    'score_agree',v_score_agree,'score_comparable',v_score_comp,
    'id_agree',v_id_agree,'id_comparable',v_id_comp,
    'minute_bad',v_minute_bad,'detail_ok',v_detail_ok
  );
end;
$$;

revoke all on function public.ft_refresh_live_shadow_compare_guard() from public,anon,authenticated;
grant execute on function public.ft_refresh_live_shadow_compare_guard() to service_role;

do $$
declare j record;
begin
  for j in select jobid from cron.job where jobname='live-shadow-compare-1min'
  loop perform cron.unschedule(j.jobid); end loop;
end $$;

select cron.schedule(
  'live-shadow-compare-1min',
  '* * * * *',
  $cron$select public.ft_refresh_live_shadow_compare_guard();$cron$
);

select public.ft_refresh_live_shadow_compare_guard();
