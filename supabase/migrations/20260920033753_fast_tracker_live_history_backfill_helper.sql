create schema if not exists private;

create or replace function private.backfill_live_history(payload jsonb)
returns integer
language plpgsql
security invoker
set search_path = public, private, pg_temp
as $$
declare
  inserted_count integer := 0;
begin
  insert into public.matches(
    hkjc_event_id,kickoff_hkt,tournament,home_en,away_en,status,selling,in_play,raw
  )
  select distinct
    x.hkjc_event_id,x.kickoff_hkt,x.league,x.home_en,x.away_en,
    'HISTORICAL_STUB',false,false,'{"live_history_backfill":true}'::jsonb
  from jsonb_to_recordset(payload) as x(
    captured_at_hkt timestamptz, api_updated_at timestamptz, hkjc_event_id text,
    kickoff_hkt timestamptz, league text, home_en text, away_en text, live_score text,
    match_minute integer, match_status text, source text, source_match_id text,
    match_confidence numeric, detail_status text, home_corners integer, away_corners integer,
    total_corners integer, corner_line_ref text, corner_progress text, team_stats jsonb,
    events jsonb, momentum jsonb, full_capture boolean, raw_full_capture_key text,
    raw_full_chunk_count integer
  )
  where x.hkjc_event_id is not null
  on conflict (hkjc_event_id) do nothing;

  insert into public.live_stats_history(
    hkjc_event_id,captured_at_hkt,api_updated_at,kickoff_hkt,league,home_en,away_en,live_score,
    match_minute,match_status,source,source_match_id,match_confidence,detail_status,
    home_corners,away_corners,total_corners,corner_line_ref,corner_progress,team_stats,events,momentum,
    full_capture,raw_full_capture_key,raw_full_chunk_count,raw
  )
  select
    x.hkjc_event_id,x.captured_at_hkt,x.api_updated_at,x.kickoff_hkt,x.league,x.home_en,x.away_en,x.live_score,
    x.match_minute,x.match_status,x.source,x.source_match_id,x.match_confidence,x.detail_status,
    x.home_corners,x.away_corners,x.total_corners,x.corner_line_ref,x.corner_progress,
    coalesce(x.team_stats,'[]'::jsonb),coalesce(x.events,'[]'::jsonb),coalesce(x.momentum,'[]'::jsonb),
    x.full_capture,x.raw_full_capture_key,x.raw_full_chunk_count,'{"legacy_sheet_backfill":true}'::jsonb
  from jsonb_to_recordset(payload) as x(
    captured_at_hkt timestamptz, api_updated_at timestamptz, hkjc_event_id text,
    kickoff_hkt timestamptz, league text, home_en text, away_en text, live_score text,
    match_minute integer, match_status text, source text, source_match_id text,
    match_confidence numeric, detail_status text, home_corners integer, away_corners integer,
    total_corners integer, corner_line_ref text, corner_progress text, team_stats jsonb,
    events jsonb, momentum jsonb, full_capture boolean, raw_full_capture_key text,
    raw_full_chunk_count integer
  )
  where x.hkjc_event_id is not null and x.captured_at_hkt is not null
  on conflict (hkjc_event_id,captured_at_hkt) do nothing;

  get diagnostics inserted_count = row_count;
  return inserted_count;
end
$$;

revoke all on schema private from public;
revoke all on function private.backfill_live_history(jsonb) from public, anon, authenticated;
grant usage on schema private to service_role;
grant execute on function private.backfill_live_history(jsonb) to service_role;
