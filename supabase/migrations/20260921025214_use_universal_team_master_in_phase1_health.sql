CREATE OR REPLACE FUNCTION public.ft_internal_app_phase1_feed(window_hours integer DEFAULT 24)
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'private', 'api', 'pg_temp'
AS $function$
with bounds as (
  select now() starts_at,
         now()+make_interval(hours=>greatest(1,least(coalesce(window_hours,24),48))) ends_at
),
markets as (
  select hkjc_event_id,
    max(line_text) filter(where source_key='HKJC' and market_key='GOALS_TOTAL') goals_line,
    max(odds) filter(where source_key='HKJC' and market_key='GOALS_TOTAL' and selection_key='OVER') goals_over,
    max(odds) filter(where source_key='HKJC' and market_key='GOALS_TOTAL' and selection_key='UNDER') goals_under,
    max(line_text) filter(where source_key='HKJC' and market_key='CORNERS_TOTAL') corners_line,
    max(odds) filter(where source_key='HKJC' and market_key='CORNERS_TOTAL' and selection_key='OVER') corners_over,
    max(odds) filter(where source_key='HKJC' and market_key='CORNERS_TOTAL' and selection_key='UNDER') corners_under,
    max(captured_at) filter(where source_key='HKJC') market_captured_at
  from private.market_current
  group by hkjc_event_id
),
evidence as (
  select hkjc_event_id,
    max(predicted_score) filter(where source_key='FOREBET' and market_key='1X2') forebet_predicted_score,
    max(prob_over) filter(where source_key='FOREBET' and market_key='OU25') forebet_ou_over,
    max(prob_under) filter(where source_key='FOREBET' and market_key='OU25') forebet_ou_under,
    max(avg_goals) filter(where source_key='FOREBET' and market_key='OU25') forebet_avg_goals,
    max(prob_over) filter(where source_key='FOREBET' and market_key='CORNERS95') forebet_corners_over,
    max(prob_under) filter(where source_key='FOREBET' and market_key='CORNERS95') forebet_corners_under,
    max(avg_corners) filter(where source_key='FOREBET' and market_key='CORNERS95') forebet_avg_corners,
    max(prob_over) filter(where source_key='MULTISOURCE' and market_key='OU25') multisource_ou_over,
    max(prob_under) filter(where source_key='MULTISOURCE' and market_key='OU25') multisource_ou_under,
    max(prob_yes) filter(where source_key='MULTISOURCE' and market_key='BTTS') multisource_btts_yes,
    max(prob_no) filter(where source_key='MULTISOURCE' and market_key='BTTS') multisource_btts_no
  from private.prediction_evidence_current
  group by hkjc_event_id
),
live as (
  select
    hkjc_event_id,fetched_at live_fetched_at,match_id,kickoff_hkt,status live_status,tournament,
    home_en,away_en,home_zh,away_zh,
    had_home live_had_home,had_draw live_had_draw,had_away live_had_away,
    hil_line live_hil_line,hil_over live_hil_over,hil_under live_hil_under,
    chl_line live_chl_line,chl_over live_chl_over,chl_under live_chl_under,
    pool_status live_pool_status,odds_updated_at live_odds_updated_at
  from public.hkjc_live_odds_current
  where pool_status='SELLINGSTARTED'
    and fetched_at >= now()-interval '10 minutes'
    and upper(coalesce(status,'')) not in ('PREEVENT','FULLTIME','FINISHED','FT','ENDED','MATCHENDED','INPLAYMATCHENDED')
),
score as (
  select
    hkjc_event_id,updated_at_source live_score_captured_at,source_updated_at live_score_source_updated_at,
    live_score,home_score,away_score,minute live_minute,match_status live_score_status,
    source live_score_source,match_confidence live_score_confidence,
    home_corners,away_corners,total_corners
  from public.live_score_current
  where updated_at_source >= now()-interval '10 minutes'
    and upper(coalesce(match_status,'')) not in ('FULLTIME','FINISHED','FT','ENDED','MATCHENDED','INPLAYMATCHENDED','AET','PEN','CANCELLED','CANCELED','VOID','ABANDONED')
    and coalesce(source,'') <> 'SOURCE_GAP'
    and coalesce(match_confidence,0) >= 0.74
),
authority as (
  select
    u.hkjc_event_id,u.kickoff_hkt,u.status,u.tournament,u.home_en,u.away_en,u.home_zh,u.away_zh,
    u.live_eligible as in_play,u.selling,
    u.had_home,u.had_draw,u.had_away,
    u.hil_line,u.hil_over,u.hil_under,
    u.chl_line,u.chl_over,u.chl_under,
    u.fetched_at authority_fetched_at,u.odds_updated_at authority_odds_updated_at,
    false as live_now
  from public.hkjc_upcoming_current u
  cross join bounds b
  where u.fetched_at >= now()-interval '30 minutes'
    and u.selling is true
    and u.kickoff_hkt >= b.starts_at
    and u.kickoff_hkt < b.ends_at

  union all

  select
    l.hkjc_event_id,l.kickoff_hkt,l.live_status,l.tournament,l.home_en,l.away_en,l.home_zh,l.away_zh,
    true as in_play,true as selling,
    null::numeric,null::numeric,null::numeric,
    null::text,null::numeric,null::numeric,
    null::text,null::numeric,null::numeric,
    l.live_fetched_at,l.live_odds_updated_at,
    true as live_now
  from live l
),
rows as (
  select
    a.hkjc_event_id,a.kickoff_hkt,
    (
      coalesce(to_jsonb(v),'{}'::jsonb)
      || jsonb_build_object(
        'hkjc_event_id',a.hkjc_event_id,
        'kickoff_hkt',a.kickoff_hkt,
        'status',a.status,
        'tournament',a.tournament,
        'home_en',a.home_en,
        'away_en',a.away_en,
        'home_zh',a.home_zh,
        'away_zh',a.away_zh,
        'in_play',a.in_play,
        'selling',a.selling,
        'hkjc_home_odds',case when a.live_now then v.hkjc_home_odds else a.had_home end,
        'hkjc_draw_odds',case when a.live_now then v.hkjc_draw_odds else a.had_draw end,
        'hkjc_away_odds',case when a.live_now then v.hkjc_away_odds else a.had_away end,
        'hkjc_novig_home',case
          when not a.live_now and a.had_home>0 and a.had_draw>0 and a.had_away>0
          then (1/a.had_home)/((1/a.had_home)+(1/a.had_draw)+(1/a.had_away))
          else v.hkjc_novig_home end,
        'hkjc_novig_draw',case
          when not a.live_now and a.had_home>0 and a.had_draw>0 and a.had_away>0
          then (1/a.had_draw)/((1/a.had_home)+(1/a.had_draw)+(1/a.had_away))
          else v.hkjc_novig_draw end,
        'hkjc_novig_away',case
          when not a.live_now and a.had_home>0 and a.had_draw>0 and a.had_away>0
          then (1/a.had_away)/((1/a.had_home)+(1/a.had_draw)+(1/a.had_away))
          else v.hkjc_novig_away end
      )
      || jsonb_build_object(
        'health_status',h.health_status,
        'primary_missing_reason',h.primary_missing_reason,
        'diagnostic_codes',(
          coalesce(
            array_remove(
              array_remove(h.diagnostic_codes,'HOME_ALIAS_NOT_REGISTERED'::text),
              'AWAY_ALIAS_NOT_REGISTERED'::text
            ),
            array[]::text[]
          )
          || case when not exists(
          select 1 from public.team_name_master tnm
          where tnm.status='VERIFIED'
            and tnm.source not in ('HKJC_EN','HKJC_ZH')
            and tnm.team_key='HKJC:'||public.ft_team_name_key(a.home_en)
        )
                  then array['HOME_ALIAS_NOT_REGISTERED'::text] else array[]::text[] end
          || case when not exists(
          select 1 from public.team_name_master tnm
          where tnm.status='VERIFIED'
            and tnm.source not in ('HKJC_EN','HKJC_ZH')
            and tnm.team_key='HKJC:'||public.ft_team_name_key(a.away_en)
        )
                  then array['AWAY_ALIAS_NOT_REGISTERED'::text] else array[]::text[] end
        ),
        'hkjc_fetched_at',a.authority_fetched_at,
        'hkjc_price_changed_at',coalesce(a.authority_odds_updated_at,h.hkjc_price_changed_at),
        'hkjc_fetch_age_minutes',extract(epoch from (now()-a.authority_fetched_at))/60.0,
        'hkjc_freshness',case
          when a.live_now then 'LIVE'
          when a.authority_fetched_at >= now()-interval '20 minutes' then 'FRESH'
          else 'STALE' end,
        'forebet_checked_at',h.forebet_checked_at,
        'forebet_state',h.forebet_state,
        'forebet_reason',h.forebet_reason,
        'forebet_check_freshness',h.forebet_check_freshness,
        'internal_model_quality',h.internal_model_quality,
        'internal_model_source',h.internal_model_source,
        'fallback_status',h.fallback_status,
        'fallback_source',h.fallback_source,
        'fallback_recommendation',h.fallback_recommendation,
        'fallback_market',h.fallback_market,
        'home_alias_present',exists(
          select 1 from public.team_name_master tnm
          where tnm.status='VERIFIED'
            and tnm.source not in ('HKJC_EN','HKJC_ZH')
            and tnm.team_key='HKJC:'||public.ft_team_name_key(a.home_en)
        ),
        'away_alias_present',exists(
          select 1 from public.team_name_master tnm
          where tnm.status='VERIFIED'
            and tnm.source not in ('HKJC_EN','HKJC_ZH')
            and tnm.team_key='HKJC:'||public.ft_team_name_key(a.away_en)
        ),
        'evidence_channel_count',h.evidence_channel_count,
        'multisource_member_count',h.multisource_member_count,
        'missing_canonical_1x2',h.missing_canonical_1x2,
        'hkjc_goals_line',case when a.live_now then m.goals_line else a.hil_line end,
        'hkjc_goals_over',case when a.live_now then m.goals_over else a.hil_over end,
        'hkjc_goals_under',case when a.live_now then m.goals_under else a.hil_under end,
        'hkjc_corners_line',case when a.live_now then m.corners_line else a.chl_line end,
        'hkjc_corners_over',case when a.live_now then m.corners_over else a.chl_over end,
        'hkjc_corners_under',case when a.live_now then m.corners_under else a.chl_under end,
        'hkjc_market_captured_at',a.authority_fetched_at,
        'forebet_predicted_score',e.forebet_predicted_score,
        'forebet_ou_over',e.forebet_ou_over,
        'forebet_ou_under',e.forebet_ou_under,
        'forebet_avg_goals',e.forebet_avg_goals,
        'forebet_corners_over',e.forebet_corners_over,
        'forebet_corners_under',e.forebet_corners_under,
        'forebet_avg_corners',e.forebet_avg_corners,
        'multisource_ou_over',e.multisource_ou_over,
        'multisource_ou_under',e.multisource_ou_under,
        'multisource_btts_yes',e.multisource_btts_yes,
        'multisource_btts_no',e.multisource_btts_no
      )
      || jsonb_build_object(
        'live_now',a.live_now,
        'live_status',l.live_status,
        'live_fetched_at',l.live_fetched_at,
        'live_pool_status',l.live_pool_status,
        'live_odds_updated_at',l.live_odds_updated_at,
        'live_had_home',l.live_had_home,
        'live_had_draw',l.live_had_draw,
        'live_had_away',l.live_had_away,
        'live_hil_line',l.live_hil_line,
        'live_hil_over',l.live_hil_over,
        'live_hil_under',l.live_hil_under,
        'live_chl_line',l.live_chl_line,
        'live_chl_over',l.live_chl_over,
        'live_chl_under',l.live_chl_under,
        'live_score',s.live_score,
        'live_home_score',s.home_score,
        'live_away_score',s.away_score,
        'live_minute',s.live_minute,
        'live_score_status',s.live_score_status,
        'live_score_source',s.live_score_source,
        'live_score_confidence',s.live_score_confidence,
        'live_score_captured_at',s.live_score_captured_at,
        'live_score_source_updated_at',s.live_score_source_updated_at,
        'live_home_corners',s.home_corners,
        'live_away_corners',s.away_corners,
        'live_total_corners',s.total_corners
      )
    ) payload
  from authority a
  left join api.phase1_match_intelligence_v v using(hkjc_event_id)
  left join private.phase1_data_health_current h using(hkjc_event_id)
  left join markets m using(hkjc_event_id)
  left join evidence e using(hkjc_event_id)
  left join live l using(hkjc_event_id)
  left join score s using(hkjc_event_id)
)
select coalesce(jsonb_agg(payload order by kickoff_hkt,hkjc_event_id),'[]'::jsonb)
from rows;
$function$
