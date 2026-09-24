create table if not exists public.live_expected_actual_history (
    hkjc_event_id text not null,
    captured_at_hkt timestamptz not null,
    segment text,
    match_minute integer,
    live_score text,
    expected_control_side text,
    actual_control_side text,
    actual_control_score integer,
    live_metric_count integer,
    shadow_status text,
    shadow_reason text,
    control_basis text,
    context_coverage_score numeric,
    xg_home numeric,
    xg_away numeric,
    shots_home numeric,
    shots_away numeric,
    sot_home numeric,
    sot_away numeric,
    possession_home numeric,
    possession_away numeric,
    box_touches_home numeric,
    box_touches_away numeric,
    big_chances_home numeric,
    big_chances_away numeric,
    corners_home numeric,
    corners_away numeric,
    source text,
    match_confidence numeric,
    created_at timestamptz not null default now(),
    primary key (hkjc_event_id,captured_at_hkt)
  );

  alter table public.live_expected_actual_history enable row level security;

  create index if not exists idx_live_expected_actual_history_event_minute
    on public.live_expected_actual_history(hkjc_event_id,match_minute);

  create index if not exists idx_live_expected_actual_history_status_time
    on public.live_expected_actual_history(shadow_status,captured_at_hkt desc);

  select cron.schedule(
    'phase3-shadow-history-5min',
    '*/5 * * * *',
    $$
    insert into public.live_expected_actual_history (
      hkjc_event_id,captured_at_hkt,segment,match_minute,live_score,
      expected_control_side,actual_control_side,actual_control_score,live_metric_count,
      shadow_status,shadow_reason,control_basis,context_coverage_score,
      xg_home,xg_away,shots_home,shots_away,sot_home,sot_away,
      possession_home,possession_away,box_touches_home,box_touches_away,
      big_chances_home,big_chances_away,corners_home,corners_away,
      source,match_confidence
    )
    select
      hkjc_event_id,captured_at_hkt,segment,match_minute,live_score,
      expected_control_side,actual_control_side,actual_control_score,live_metric_count,
      shadow_status,shadow_reason,control_basis,context_coverage_score,
      xg_home,xg_away,shots_home,shots_away,sot_home,sot_away,
      possession_home,possession_away,box_touches_home,box_touches_away,
      big_chances_home,big_chances_away,corners_home,corners_away,
      source,match_confidence
    from public.live_expected_actual_current
    where coalesce(match_minute,0) >= 10
      and live_metric_count >= 3
    on conflict (hkjc_event_id,captured_at_hkt) do nothing;
    $$
  );
