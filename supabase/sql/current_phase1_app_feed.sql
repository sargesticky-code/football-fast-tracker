-- Current deployed Phase 1 app-feed RPC definition.
-- Kept outside migrations because the live database was repaired in-place during recovery.
-- Promote through a generated Supabase migration before the next schema release.
create or replace function public.ft_internal_app_phase1_feed(window_hours integer default 24)
returns jsonb language sql security definer
set search_path to 'pg_catalog','public','private','api','pg_temp'
as $$
with bounds as (
 select now() starts_at, now()+make_interval(hours=>greatest(1,least(coalesce(window_hours,24),48))) ends_at
), markets as (
 select hkjc_event_id,
 max(line_text) filter(where source_key='HKJC' and market_key='GOALS_TOTAL') goals_line,
 max(odds) filter(where source_key='HKJC' and market_key='GOALS_TOTAL' and selection_key='OVER') goals_over,
 max(odds) filter(where source_key='HKJC' and market_key='GOALS_TOTAL' and selection_key='UNDER') goals_under,
 max(line_text) filter(where source_key='HKJC' and market_key='CORNERS_TOTAL') corners_line,
 max(odds) filter(where source_key='HKJC' and market_key='CORNERS_TOTAL' and selection_key='OVER') corners_over,
 max(odds) filter(where source_key='HKJC' and market_key='CORNERS_TOTAL' and selection_key='UNDER') corners_under,
 max(captured_at) filter(where source_key='HKJC') market_captured_at
 from private.market_current group by hkjc_event_id
), evidence as (
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
 from private.prediction_evidence_current group by hkjc_event_id
), rows as (
 select v.hkjc_event_id,v.kickoff_hkt,
 to_jsonb(v)||jsonb_build_object(
 'health_status',h.health_status,'primary_missing_reason',h.primary_missing_reason,'diagnostic_codes',h.diagnostic_codes,
 'hkjc_fetched_at',h.hkjc_fetched_at,'hkjc_price_changed_at',h.hkjc_price_changed_at,'hkjc_fetch_age_minutes',h.hkjc_fetch_age_minutes,
 'hkjc_freshness',h.hkjc_freshness,'forebet_checked_at',h.forebet_checked_at,'forebet_state',h.forebet_state,'forebet_reason',h.forebet_reason,
 'forebet_check_freshness',h.forebet_check_freshness,'internal_model_quality',h.internal_model_quality,'internal_model_source',h.internal_model_source,
 'fallback_status',h.fallback_status,'fallback_source',h.fallback_source,'fallback_recommendation',h.fallback_recommendation,'fallback_market',h.fallback_market,
 'home_alias_present',h.home_alias_present,'away_alias_present',h.away_alias_present,'evidence_channel_count',h.evidence_channel_count,
 'multisource_member_count',h.multisource_member_count,'missing_canonical_1x2',h.missing_canonical_1x2,
 'hkjc_goals_line',m.goals_line,'hkjc_goals_over',m.goals_over,'hkjc_goals_under',m.goals_under,
 'hkjc_corners_line',m.corners_line,'hkjc_corners_over',m.corners_over,'hkjc_corners_under',m.corners_under,'hkjc_market_captured_at',m.market_captured_at,
 'forebet_predicted_score',e.forebet_predicted_score,'forebet_ou_over',e.forebet_ou_over,'forebet_ou_under',e.forebet_ou_under,
 'forebet_avg_goals',e.forebet_avg_goals,'forebet_corners_over',e.forebet_corners_over,'forebet_corners_under',e.forebet_corners_under,
 'forebet_avg_corners',e.forebet_avg_corners,'multisource_ou_over',e.multisource_ou_over,'multisource_ou_under',e.multisource_ou_under,
 'multisource_btts_yes',e.multisource_btts_yes,'multisource_btts_no',e.multisource_btts_no
 ) payload
 from api.phase1_match_intelligence_v v cross join bounds b
 left join private.phase1_data_health_current h using(hkjc_event_id)
 left join markets m using(hkjc_event_id) left join evidence e using(hkjc_event_id)
 where v.selling is true and v.kickoff_hkt>=b.starts_at and v.kickoff_hkt<b.ends_at
)
select coalesce(jsonb_agg(payload order by kickoff_hkt,hkjc_event_id),'[]'::jsonb) from rows;
$$;
revoke execute on function public.ft_internal_app_phase1_feed(integer) from public,anon,authenticated;
grant execute on function public.ft_internal_app_phase1_feed(integer) to service_role;
