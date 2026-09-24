
    create or replace view public.system_health_current_v
    with (security_invoker = true)
    as
    with expected(source,metric,component,max_age_minutes,priority) as (
      values
        ('HKJC_LIVE_EDGE'::text,'heartbeat'::text,'HKJC Live'::text,3::numeric,1),
        ('LIVE_SCORE_EDGE','heartbeat','Live Score',3,1),
        ('LIVE_LAYER_GUARD','heartbeat','Live Layer',3,1),
        ('LIVE_SOURCE_SHADOW','heartbeat','Live Shadow Source',5,2),
        ('LIVE_SHADOW_COMPARE','heartbeat','Live Shadow Compare',3,2),
        ('HKJC_UPCOMING_EDGE','heartbeat','HKJC Upcoming',25,1),
        ('FRONTEND_ROUTE_GUARD','heartbeat','Frontend Routes',10,1),
        ('PHASE1_COVERAGE_GUARD','48h','Phase 1 Coverage',30,2),
        ('API_FOOTBALL_PHASE2','base','Phase 2 Base',390,2),
        ('API_FOOTBALL_PHASE2','detail','Phase 2 Detail',45,2),
        ('TEAM_ALIAS_V2','registry','Alias Registry',90,2),
        ('GITHUB_OIDC_INGEST','forebet_current.csv','Forebet Feed',1560,2),
        ('FOOTBALL_DATA_EDGE','heartbeat','Football-Data',1620,3)
    ),
    source_rows as (
      select
        e.component,
        e.priority,
        e.max_age_minutes,
        h.source,
        h.metric,
        h.status as raw_status,
        h.value_text,
        h.notes,
        h.observed_at,
        case when h.observed_at is null then null
             else round(extract(epoch from (now()-h.observed_at))/60.0,1)
        end as age_minutes
      from expected e
      left join public.source_health h
        on h.source=e.source and h.metric=e.metric
    ),
    normalized as (
      select
        component,priority,source,metric,raw_status,value_text,notes,observed_at,
        age_minutes,max_age_minutes,
        case
          when observed_at is null then 'MISSING'
          when age_minutes > max_age_minutes then 'STALE'
          when upper(coalesce(raw_status,'')) in ('FAIL','FAILED','ERROR','STALE','CRITICAL') then 'FAIL'
          when upper(coalesce(raw_status,'')) in ('WARN','WARNING','DEGRADED','PARTIAL') then 'WARN'
          when upper(coalesce(raw_status,'')) in
            ('OK','PASS','SUCCESS','ACTIVE','IDLE','WAITING_LINEUP','QUOTA_GUARD','INFO') then 'OK'
          else 'INFO'
        end as health_state
      from source_rows
    ),
    polymarket as (
      select
        'Polymarket'::text as component,
        2 as priority,
        'POLYMARKET'::text as source,
        'market_quotes'::text as metric,
        p.last_status as raw_status,
        p.last_row_count::text as value_text,
        p.last_error as notes,
        coalesce(p.last_success_at,p.last_attempt_at,p.updated_at) as observed_at,
        case when coalesce(p.last_success_at,p.last_attempt_at,p.updated_at) is null then null
             else round(extract(epoch from (now()-coalesce(p.last_success_at,p.last_attempt_at,p.updated_at)))/60.0,1)
        end as age_minutes,
        5::numeric as max_age_minutes,
        case
          when coalesce(p.last_success_at,p.last_attempt_at,p.updated_at) is null then 'MISSING'
          when extract(epoch from (now()-coalesce(p.last_success_at,p.last_attempt_at,p.updated_at)))/60.0 > 5 then 'STALE'
          when upper(coalesce(p.last_status,'')) in ('FAIL','FAILED','ERROR') then 'FAIL'
          when upper(coalesce(p.last_status,'')) in ('WARN','WARNING','DEGRADED') then 'WARN'
          when upper(coalesce(p.last_status,''))='SUCCESS' then 'OK'
          else 'INFO'
        end as health_state
      from phase4.provider_ingest_health p
      where p.provider_id='POLYMARKET'
    )
    select * from normalized
    union all
    select * from polymarket;

    revoke all on public.system_health_current_v from public, anon, authenticated;
    grant select on public.system_health_current_v to service_role;

    comment on view public.system_health_current_v is
      'Backend-only unified freshness/status view. Distinguishes source health from cron dispatch success.';
  
