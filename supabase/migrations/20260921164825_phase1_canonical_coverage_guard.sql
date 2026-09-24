
create or replace function public.ft_refresh_phase1_coverage_guard()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, private, pg_temp
as $$
declare
  v_target_count integer := 0;
  v_missing_availability integer := 0;
  v_forebet_models integer := 0;
  v_fixture_only integer := 0;
  v_source_absent integer := 0;
  v_stale_forebet integer := 0;
  v_zero_evidence integer := 0;
  v_missing_ids text[] := array[]::text[];
  v_zero_evidence_ids text[] := array[]::text[];
  v_status text;
  v_payload jsonb;
begin
  with targets as (
    select u.hkjc_event_id
    from public.hkjc_upcoming_current u
    where u.fetched_at >= now() - interval '30 minutes'
      and u.selling is true
      and u.kickoff_hkt >= now()
      and u.kickoff_hkt < now() + interval '48 hours'
  ),
  coverage as (
    select
      t.hkjc_event_id,
      fa.state as forebet_state,
      fa.checked_at as forebet_checked_at,
      (fp.hkjc_event_id is not null
        and fp.prob_home is not null
        and fp.prob_draw is not null
        and fp.prob_away is not null) as has_forebet_model,
      coalesce(h.evidence_channel_count,0) as evidence_channel_count
    from targets t
    left join public.forebet_availability fa using (hkjc_event_id)
    left join public.forebet_predictions fp using (hkjc_event_id)
    left join private.phase1_data_health_current h using (hkjc_event_id)
  )
  select
    count(*)::int,
    count(*) filter (where forebet_state is null)::int,
    count(*) filter (where has_forebet_model)::int,
    count(*) filter (where forebet_state = 'FIXTURE_ONLY')::int,
    count(*) filter (where forebet_state = 'UNRESOLVED')::int,
    count(*) filter (
      where forebet_state is not null
        and (forebet_checked_at is null or forebet_checked_at < now() - interval '14 hours')
    )::int,
    count(*) filter (where evidence_channel_count = 0)::int,
    coalesce(array_agg(hkjc_event_id order by hkjc_event_id)
      filter (where forebet_state is null), array[]::text[]),
    coalesce(array_agg(hkjc_event_id order by hkjc_event_id)
      filter (where evidence_channel_count = 0), array[]::text[])
  into
    v_target_count,
    v_missing_availability,
    v_forebet_models,
    v_fixture_only,
    v_source_absent,
    v_stale_forebet,
    v_zero_evidence,
    v_missing_ids,
    v_zero_evidence_ids
  from coverage;

  v_status := case
    when v_target_count = 0 then 'WARN'
    when v_missing_availability > 0 then 'FAIL'
    when v_stale_forebet > 0 or v_zero_evidence > 0 then 'WARN'
    else 'PASS'
  end;

  v_payload := jsonb_build_object(
    'window_hours', 48,
    'target_count', v_target_count,
    'missing_forebet_availability', v_missing_availability,
    'forebet_model_count', v_forebet_models,
    'forebet_fixture_only_count', v_fixture_only,
    'forebet_source_absent_count', v_source_absent,
    'stale_forebet_checks', v_stale_forebet,
    'zero_independent_evidence_count', v_zero_evidence,
    'missing_availability_ids', to_jsonb(v_missing_ids[1:50]),
    'zero_evidence_ids', to_jsonb(v_zero_evidence_ids[1:50])
  );

  insert into public.source_health(
    source, metric, value_text, status, notes, observed_at, raw
  )
  values (
    'PHASE1_COVERAGE_GUARD',
    '48h',
    v_payload::text,
    v_status,
    case
      when v_missing_availability > 0 then
        'Canonical HKJC targets exist without Forebet availability classification; upstream recovery required.'
      when v_zero_evidence > 0 then
        'Canonical target coverage is classified, but some matches have no independent prediction evidence.'
      else
        'Canonical 48h target coverage is classified and independent evidence is available.'
    end,
    now(),
    v_payload
  )
  on conflict (source, metric) do update
  set value_text = excluded.value_text,
      status = excluded.status,
      notes = excluded.notes,
      observed_at = excluded.observed_at,
      raw = excluded.raw;

  return v_payload || jsonb_build_object('status', v_status);
end
$$;

revoke all on function public.ft_refresh_phase1_coverage_guard() from public;
revoke all on function public.ft_refresh_phase1_coverage_guard() from anon;
revoke all on function public.ft_refresh_phase1_coverage_guard() from authenticated;
grant execute on function public.ft_refresh_phase1_coverage_guard() to service_role;

do $$
declare
  r record;
begin
  for r in select jobid from cron.job where jobname = 'phase1-coverage-guard-15min'
  loop
    perform cron.unschedule(r.jobid);
  end loop;
end
$$;

select cron.schedule(
  'phase1-coverage-guard-15min',
  '4,19,34,49 * * * *',
  'select public.ft_refresh_phase1_coverage_guard();'
);
