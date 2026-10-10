-- Production migration 20261010152805. Existing cron37 refreshed, no new cron.
CREATE OR REPLACE FUNCTION private.ft_safe_refresh_phase1_core()
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public', 'private', 'api', 'pg_temp'
AS $function$
begin
  begin
    -- Legacy internal Phase1 function was dropped; execute the two existing
    -- independently verified refresh functions directly.
    perform public.ft_refresh_cloud_market_current();
    perform public.ft_refresh_cloud_odds_movement();

    insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
    values(
      'PHASE1_CORE_REFRESH','decoupled','OK','OK',
      'Phase 1 core refresh completed with cloud Bet365 market authority and independent prediction evidence.',
      now(),
      jsonb_build_object('mode','CLOUD_MARKET_AUTHORITY','market_source','FLASHSCORE_BET365')
    )
    on conflict(source,metric) do update set
      value_text=excluded.value_text,
      status=excluded.status,
      notes=excluded.notes,
      observed_at=excluded.observed_at,
      raw=excluded.raw;
  exception when others then
    insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
    values(
      'PHASE1_CORE_REFRESH','decoupled',sqlerrm,'WARN',
      'Phase 1 core refresh failed; cloud bookmaker staging/current data is preserved independently.',
      now(),
      jsonb_build_object('mode','CLOUD_MARKET_AUTHORITY','sqlstate',sqlstate,'error',sqlerrm)
    )
    on conflict(source,metric) do update set
      value_text=excluded.value_text,
      status=excluded.status,
      notes=excluded.notes,
      observed_at=excluded.observed_at,
      raw=excluded.raw;
  end;
end
$function$
;
