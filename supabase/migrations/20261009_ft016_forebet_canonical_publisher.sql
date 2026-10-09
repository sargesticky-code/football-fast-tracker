
-- FT016 Forebet-only canonical publication; no legacy CSV or HKJC authority restoration.
CREATE OR REPLACE FUNCTION public.ft_publish_forebet_canonical(p_rows jsonb, p_run_id text)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, public, private, pg_temp
AS $fn$
DECLARE
  r jsonb; f record; id text; ts timestamptz; ko timestamptz;
  h numeric; d numeric; a numeric; pick text; score text; capture_count integer;
  applied integer := 0; skipped integer := 0;
BEGIN
  IF jsonb_typeof(p_rows) IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_rows) NOT BETWEEN 1 AND 500
     OR coalesce(p_run_id,'') !~ '^[0-9]{6,20} THEN
    RAISE EXCEPTION 'INVALID_FOREBET_BATCH';
  END IF;
  capture_count := jsonb_array_length(p_rows);
  IF (SELECT count(DISTINCT x->>'match_id') FROM jsonb_array_elements(p_rows) x) <> capture_count THEN
    RAISE EXCEPTION 'DUPLICATE_FOREBET_FIXTURE';
  END IF;
  -- Validate the entire batch before any modifications.
  FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
    id := r->>'match_id';
    IF id IS NULL OR id = '' OR id !~ '^[A-Za-z0-9:_-]{2,80}$' THEN
      RAISE EXCEPTION 'INVALID_FOREBET_ID';
    END IF;
    BEGIN
      ts := (r->>'captured_at')::timestamptz;
      ko := (r->>'kickoff')::timestamptz;
      h := (r->>'home')::numeric;
      d := (r->>'draw')::numeric;
      a := (r->>'away')::numeric;
    EXCEPTION WHEN others THEN
      RAISE EXCEPTION 'INVALID_FOREBET_FIELDS %',id;
    END;
    pick := r->>'pick';
    score := r->>'score';
    IF ts IS NULL OR ts < now() - interval '72 hours'
       OR ts > now() + interval '10 minutes'
       OR h IS NULL OR d IS NULL OR a IS NULL
       OR h NOT BETWEEN 0 AND 100 OR d NOT BETWEEN 0 AND 100
       OR a NOT BETWEEN 0 AND 100 OR h+d+a NOT BETWEEN 98 AND 102
       OR pick NOT IN ('1','X','2')
       OR score IS NULL OR score !~ '^[0-9]{1,2} *- *[0-9]{1,2}$'
       OR coalesce((r->>'match_score')::numeric,0) < 0.94 THEN
      RAISE EXCEPTION 'INVALID_FOREBET_MODEL %',id;
    END IF;
    SELECT match_id,home_en,away_en,kickoff_hkt INTO f
      FROM public.active_canonical_fixture_current
      WHERE match_id=id;
    IF NOT FOUND OR ko IS DISTINCT FROM f.kickoff_hkt
      OR trim(lower(coalesce(r->>'canonical_home',''))) IS DISTINCT FROM trim(lower(f.home_en))
      OR trim(lower(coalesce(r->>'canonical_away',''))) IS DISTINCT FROM trim(lower(f.away_en))
      OR NOT EXISTS (SELECT 1 FROM public.matches m WHERE m.hkjc_event_id=id)
      OR NOT EXISTS (SELECT 1 FROM public.forebet_availability av WHERE av.match_id=id)
      OR ko < now()-interval '12 hours' OR ko > now()+interval '15 days' THEN
      RAISE EXCEPTION 'FOREBET_FIXTURE_IDENTITY_MISMATCH %',id;
    END IF;
  END LOOP;
  FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
    id:=r->>'match_id';
    ts:=(r->>'captured_at')::timestamptz;
    h:=(r->>'home')::numeric;d:=(r->>'draw')::numeric;a:=(r->>'away')::numeric;
    pick:=r->>'pick';score:=r->>'score';
    INSERT INTO public.forebet_predictions (
      hkjc_event_id,fetched_at,forebet_match_date,forebet_kickoff_text,
      forebet_league_short,forebet_home_team,forebet_away_team,
      prob_home,prob_draw,prob_away,prediction_1x2,predicted_score,match_score,raw,updated_at)
    VALUES (
      id,ts,r->>'match_date',r->>'kickoff_text',r->>'league',
      r->>'source_home',r->>'source_away',h,d,a,pick,score,
      (r->>'match_score')::numeric,
      jsonb_build_object('source','FOREBET','captured_at',ts,'publication_run',p_run_id),
      now())
    ON CONFLICT (hkjc_event_id) DO UPDATE SET
      fetched_at=excluded.fetched_at,forebet_match_date=excluded.forebet_match_date,
      forebet_kickoff_text=excluded.forebet_kickoff_text,
      forebet_league_short=excluded.forebet_league_short,
      forebet_home_team=excluded.forebet_home_team,forebet_away_team=excluded.forebet_away_team,
      prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
      prediction_1x2=excluded.prediction_1x2,predicted_score=excluded.predicted_score,
      match_score=excluded.match_score,raw=excluded.raw,
      prediction_ou25=NULL, prob_over25=NULL,prob_under25=NULL,
      ou_predicted_score=NULL,corner_prediction=NULL,corner_prob_under95=NULL,
      corner_prob_over95=NULL,corner_predicted_score=NULL,avg_goals=NULL,
      avg_corners=NULL,forebet_detail_url=NULL,updated_at=now()
    WHERE public.forebet_predictions.fetched_at IS NULL
       OR public.forebet_predictions.fetched_at < excluded.fetched_at;
    IF FOUND THEN
      applied:=applied+1;
      INSERT INTO private.prediction_evidence_current(
        hkjc_event_id,source_key,market_key,source_updated_at,
        status,pick,predicted_score,prob_home,prob_draw,prob_away,
        source_count,source_members,confidence,raw,updated_at)
      VALUES(
        id,'FOREBET','1X2',ts,'CURRENT',pick,score,h/100,d/100,a/100,
        1,ARRAY['FOREBET'],(r->>'match_score')::numeric,
        jsonb_build_object('source','FOREBET','captured_at',ts,'publication_run',p_run_id),now())
      ON CONFLICT(hkjc_event_id,source_key,market_key) DO UPDATE SET
        source_updated_at=excluded.source_updated_at,status='CURRENT',
        pick=excluded.pick,predicted_score=excluded.predicted_score,
        prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
        source_count=excluded.source_count,source_members=excluded.source_members,
        confidence=excluded.confidence,raw=excluded.raw,updated_at=now()
      WHERE private.prediction_evidence_current.source_updated_at IS NULL
         OR private.prediction_evidence_current.source_updated_at < excluded.source_updated_at;
      UPDATE public.forebet_availability
        SET state='MODEL',checked_at=ts,reason='FOREBET_VERIFIED_CAPTURE',
            raw=coalesce(raw,'{}'::jsonb)||jsonb_build_object('publication_run',p_run_id,'captured_at',ts),
            updated_at=now()
        WHERE match_id=id AND (state IS DISTINCT FROM 'MODEL' OR checked_at IS NULL OR checked_at < ts);
    ELSE
      skipped:=skipped+1;
    END IF;
  END LOOP;
  RETURN jsonb_build_object('accepted',capture_count,'applied',applied,'unchanged',skipped,'run',p_run_id);
END;
$fn$;
REVOKE ALL ON FUNCTION public.ft_publish_forebet_canonical(jsonb,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ft_publish_forebet_canonical(jsonb,text) TO service_role;
 THEN
    RAISE EXCEPTION 'INVALID_FOREBET_BATCH';
  END IF;
  capture_count := jsonb_array_length(p_rows);
  IF (SELECT count(DISTINCT x->>'match_id') FROM jsonb_array_elements(p_rows) x) <> capture_count THEN
    RAISE EXCEPTION 'DUPLICATE_FOREBET_FIXTURE';
  END IF;
  -- Validate the entire batch before any modifications.
  FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
    id := r->>'match_id';
    IF id IS NULL OR id = '' OR id !~ '^[A-Za-z0-9:_-]{2,80}$' THEN
      RAISE EXCEPTION 'INVALID_FOREBET_ID';
    END IF;
    BEGIN
      ts := (r->>'captured_at')::timestamptz;
      ko := (r->>'kickoff')::timestamptz;
      h := (r->>'home')::numeric;
      d := (r->>'draw')::numeric;
      a := (r->>'away')::numeric;
    EXCEPTION WHEN others THEN
      RAISE EXCEPTION 'INVALID_FOREBET_FIELDS %',id;
    END;
    pick := r->>'pick';
    score := r->>'score';
    IF ts IS NULL OR ts < now() - interval '72 hours'
       OR ts > now() + interval '10 minutes'
       OR h IS NULL OR d IS NULL OR a IS NULL
       OR h NOT BETWEEN 0 AND 100 OR d NOT BETWEEN 0 AND 100
       OR a NOT BETWEEN 0 AND 100 OR h+d+a NOT BETWEEN 98 AND 102
       OR pick NOT IN ('1','X','2')
       OR score IS NULL OR score !~ '^[0-9]{1,2} *- *[0-9]{1,2}$'
       OR coalesce((r->>'match_score')::numeric,0) < 0.94 THEN
      RAISE EXCEPTION 'INVALID_FOREBET_MODEL %',id;
    END IF;
    SELECT match_id,home_en,away_en,kickoff_hkt INTO f
      FROM public.active_canonical_fixture_current
      WHERE match_id=id;
    IF NOT FOUND OR ko IS DISTINCT FROM f.kickoff_hkt
      OR trim(lower(coalesce(r->>'canonical_home',''))) IS DISTINCT FROM trim(lower(f.home_en))
      OR trim(lower(coalesce(r->>'canonical_away',''))) IS DISTINCT FROM trim(lower(f.away_en))
      OR NOT EXISTS (SELECT 1 FROM public.matches m WHERE m.hkjc_event_id=id)
      OR NOT EXISTS (SELECT 1 FROM public.forebet_availability av WHERE av.match_id=id)
      OR ko < now()-interval '12 hours' OR ko > now()+interval '15 days' THEN
      RAISE EXCEPTION 'FOREBET_FIXTURE_IDENTITY_MISMATCH %',id;
    END IF;
  END LOOP;
  FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
    id:=r->>'match_id';
    ts:=(r->>'captured_at')::timestamptz;
    h:=(r->>'home')::numeric;d:=(r->>'draw')::numeric;a:=(r->>'away')::numeric;
    pick:=r->>'pick';score:=r->>'score';
    INSERT INTO public.forebet_predictions (
      hkjc_event_id,fetched_at,forebet_match_date,forebet_kickoff_text,
      forebet_league_short,forebet_home_team,forebet_away_team,
      prob_home,prob_draw,prob_away,prediction_1x2,predicted_score,match_score,raw,updated_at)
    VALUES (
      id,ts,r->>'match_date',r->>'kickoff_text',r->>'league',
      r->>'source_home',r->>'source_away',h,d,a,pick,score,
      (r->>'match_score')::numeric,
      jsonb_build_object('source','FOREBET','captured_at',ts,'publication_run',p_run_id),
      now())
    ON CONFLICT (hkjc_event_id) DO UPDATE SET
      fetched_at=excluded.fetched_at,forebet_match_date=excluded.forebet_match_date,
      forebet_kickoff_text=excluded.forebet_kickoff_text,
      forebet_league_short=excluded.forebet_league_short,
      forebet_home_team=excluded.forebet_home_team,forebet_away_team=excluded.forebet_away_team,
      prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
      prediction_1x2=excluded.prediction_1x2,predicted_score=excluded.predicted_score,
      match_score=excluded.match_score,raw=excluded.raw,updated_at=now()
    WHERE public.forebet_predictions.fetched_at IS NULL
       OR public.forebet_predictions.fetched_at < excluded.fetched_at;
    IF FOUND THEN
      applied:=applied+1;
      INSERT INTO private.prediction_evidence_current(
        hkjc_event_id,source_key,market_key,source_updated_at,
        status,pick,predicted_score,prob_home,prob_draw,prob_away,
        source_count,source_members,confidence,raw,updated_at)
      VALUES(
        id,'FOREBET','1X2',ts,'CURRENT',pick,score,h/100,d/100,a/100,
        1,ARRAY['FOREBET'],(r->>'match_score')::numeric,
        jsonb_build_object('source','FOREBET','captured_at',ts,'publication_run',p_run_id),now())
      ON CONFLICT(hkjc_event_id,source_key,market_key) DO UPDATE SET
        source_updated_at=excluded.source_updated_at,status='CURRENT',
        pick=excluded.pick,predicted_score=excluded.predicted_score,
        prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
        source_count=excluded.source_count,source_members=excluded.source_members,
        confidence=excluded.confidence,raw=excluded.raw,updated_at=now()
      WHERE private.prediction_evidence_current.source_updated_at IS NULL
         OR private.prediction_evidence_current.source_updated_at < excluded.source_updated_at;
      UPDATE public.forebet_availability
        SET state='MODEL',checked_at=ts,reason='FOREBET_VERIFIED_CAPTURE',updated_at=now()
        WHERE match_id=id AND (state IS DISTINCT FROM 'MODEL' OR checked_at IS NULL OR checked_at < ts);
    ELSE
      skipped:=skipped+1;
    END IF;
  END LOOP;
  RETURN jsonb_build_object('accepted',capture_count,'applied',applied,'unchanged',skipped,'run',p_run_id);
END;
$fn$;
REVOKE ALL ON FUNCTION public.ft_publish_forebet_canonical(jsonb,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ft_publish_forebet_canonical(jsonb,text) TO service_role;
