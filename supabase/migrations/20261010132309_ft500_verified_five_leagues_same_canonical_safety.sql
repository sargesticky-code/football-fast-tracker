-- Supabase production applied 20261010132309 (2026-10-10).
-- Exact verified 500.com SPF for EPL, LaLiga, Serie A, Bundesliga, Ligue 1.
-- Replaces stored RPCs only, same service-only RLS table, Edge + GitHub OIDC.
CREATE OR REPLACE FUNCTION public.ft_publish_500_spf(p_rows jsonb, p_run_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
  n integer;
  r jsonb;
  mid text;
  incoming_source_id text;
  resolved_league text;
  kickoff timestamptz;
  captured timestamptz;
  source_updated timestamptz;
  h numeric; d numeric; a numeric;
  affected integer := 0;
  written integer := 0;
  seen_ids text[] := ARRAY[]::text[];
  seen_source_ids text[] := ARRAY[]::text[];
BEGIN
  IF p_run_id !~ '^[0-9]{6,20}$' THEN
    RAISE EXCEPTION 'invalid run provenance';
  END IF;
  IF jsonb_typeof(p_rows) <> 'array' OR jsonb_array_length(p_rows) NOT BETWEEN 1 AND 100 THEN
    RAISE EXCEPTION 'invalid payload size';
  END IF;
  n := jsonb_array_length(p_rows);
  FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
    mid := r->>'match_id';
    incoming_source_id := r->>'source_event_id';
    resolved_league := nullif(r->>'canonical_league','');
    IF resolved_league IS NULL AND r->>'source_league'='英格兰超级联赛' THEN
      resolved_league := 'EPL';
    END IF;
    IF mid IS NULL OR mid !~ '^[A-Za-z0-9:_-]{2,80}$'
      OR incoming_source_id IS NULL OR incoming_source_id !~ '^[0-9]{5,15}$'
      OR coalesce(r->>'source_matchnum','') !~ '^[0-9]{3,8}$'
      OR resolved_league IS NULL
      OR NOT coalesce((
        (r->>'source_league'='英格兰超级联赛' AND resolved_league='EPL') OR
        (r->>'source_league'='西班牙甲级联赛' AND resolved_league LIKE 'LaLigaSPAIN:%') OR
        (r->>'source_league'='意大利甲级联赛' AND resolved_league LIKE 'Serie AITALY:%') OR
        (r->>'source_league'='德国甲级联赛' AND resolved_league LIKE 'BundesligaGERMANY:%') OR
        (r->>'source_league'='法国甲级联赛' AND resolved_league LIKE 'Ligue 1FRANCE:%')
      ),false)
      OR r->>'provider' IS DISTINCT FROM 'CHINA_500_SPF'
      OR r->>'identity_method' IS DISTINCT FROM 'VERIFIED_TEAM_PAIR_AND_KICKOFF'
      OR nullif(r->>'source_home','') IS NULL OR nullif(r->>'source_away','') IS NULL
      OR mid=ANY(seen_ids) OR incoming_source_id=ANY(seen_source_ids)
    THEN
      RAISE EXCEPTION 'invalid/duplicate source identity';
    END IF;
    seen_ids := array_append(seen_ids,mid);
    seen_source_ids := array_append(seen_source_ids,incoming_source_id);
    kickoff := (r->>'kickoff')::timestamptz;
    captured := (r->>'captured_at')::timestamptz;
    source_updated := (r->>'source_updated_at')::timestamptz;
    h := (r->>'home')::numeric; d := (r->>'draw')::numeric; a := (r->>'away')::numeric;
    IF kickoff IS NULL OR captured IS NULL OR source_updated IS NULL
       OR captured NOT BETWEEN now()-interval '30 minutes' AND now()+interval '5 minutes'
       OR kickoff NOT BETWEEN now()-interval '2 hours' AND now()+interval '48 hours'
       OR source_updated NOT BETWEEN now()-interval '14 days' AND captured+interval '5 minutes'
       OR h NOT BETWEEN 1.01 AND 100 OR d NOT BETWEEN 1.01 AND 100 OR a NOT BETWEEN 1.01 AND 100
       OR NOT EXISTS (
         SELECT 1 FROM public.active_canonical_fixture_current f
         WHERE f.match_id=mid AND f.league=resolved_league
           AND f.home_en=r->>'canonical_home' AND f.away_en=r->>'canonical_away'
           AND abs(extract(epoch FROM (f.kickoff_hkt-kickoff)))<=600
       )
    THEN
      RAISE EXCEPTION 'source freshness, pricing or canonical identity failed';
    END IF;
    INSERT INTO public.ft_500_spf_current AS existing (
      match_id,source_event_id,source_matchnum,source_home,source_away,
      league,kickoff_hkt,home,draw,away,source_updated_at,captured_at,updated_at
    ) VALUES (
      mid,incoming_source_id,r->>'source_matchnum',r->>'source_home',r->>'source_away',
      resolved_league,kickoff,h,d,a,source_updated,captured,now()
    )
    ON CONFLICT (match_id) DO UPDATE SET
      home=EXCLUDED.home,draw=EXCLUDED.draw,away=EXCLUDED.away,
      source_updated_at=EXCLUDED.source_updated_at,
      captured_at=EXCLUDED.captured_at,updated_at=now()
    WHERE existing.source_event_id=EXCLUDED.source_event_id
      AND existing.league=EXCLUDED.league
      AND existing.source_updated_at <= EXCLUDED.source_updated_at
      AND existing.captured_at <= EXCLUDED.captured_at;
    GET DIAGNOSTICS affected=ROW_COUNT;
    written := written+affected;
  END LOOP;
  RETURN jsonb_build_object('source','CHINA_500_SPF','accepted',n,'written',written);
END;
$function$
;
CREATE OR REPLACE FUNCTION public.ft_fast_flashscore_summary(p_window_hours integer DEFAULT 24)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO 'public', 'pg_temp'
AS $function$
 select coalesce(jsonb_agg(
  jsonb_build_object(
   'match_id',f.match_id,'kickoff_hkt',f.kickoff_hkt,'status',f.status,
   'tournament',f.league,'home_en',f.home_en,'away_en',f.away_en,
   'fetched_at',b.fetched_at,'updated_at',coalesce(b.updated_at,f.updated_at),
   'had_home',b.bet365_home,'had_draw',b.bet365_draw,'had_away',b.bet365_away,
   'odds_updated_at',b.fetched_at,'detail_raw',d.detail_raw,
   'detail_fetched_at',d.detail_fetched_at,
   'forebet_captured_at',fb.fetched_at,
   'forebet_home',fb.prob_home / 100.0,
   'forebet_draw',fb.prob_draw / 100.0,
   'forebet_away',fb.prob_away / 100.0,
   'forebet_predicted_score',fb.predicted_score,
   'forebet_avg_goals',fb.avg_goals,
   'china500_home',c.home,'china500_draw',c.draw,'china500_away',c.away,
   'china500_captured_at',c.captured_at,'china500_source_updated_at',c.source_updated_at
  ) order by f.kickoff_hkt,f.match_id
 ),'[]'::jsonb)
 from public.active_canonical_fixture_current f
 left join public.bookmaker_odds_current b on b.match_id=f.match_id
 left join lateral (
   select s.detail_raw,s.detail_fetched_at
   from public.phase15_source_shadow_current s
   where s.match_id=f.match_id and s.source_key='FLASHSCORE'
     and s.detail_fetched_at>now()-interval '24 hours'
   order by s.detail_fetched_at desc nulls last limit 1
 ) d on true
 left join public.forebet_predictions fb
   on fb.hkjc_event_id=f.match_id
   and fb.fetched_at >= now()-interval '72 hours'
   and fb.fetched_at <= now()+interval '10 minutes'
   and fb.match_score >= 0.94
   and fb.prob_home between 0 and 100
   and fb.prob_draw between 0 and 100
   and fb.prob_away between 0 and 100
   and fb.prob_home+fb.prob_draw+fb.prob_away between 98 and 102
   and fb.predicted_score ~ '^[0-9]{1,2} *- *[0-9]{1,2}$'
   and fb.avg_goals > 0 and fb.avg_goals <= 12
 left join public.ft_500_spf_current c on c.match_id=f.match_id
   and c.league=f.league
   and c.captured_at >= now()-interval '75 minutes'
   and c.source_updated_at >= now()-interval '24 hours'
   and c.source_updated_at <= now()+interval '5 minutes'
 where f.kickoff_hkt >= now()-interval '6 hours'
   and f.kickoff_hkt < now() + make_interval(hours => greatest(1,least(48,p_window_hours)));
$function$
;
