-- Forebet publisher verified Flashscore contract. Deployed and checked 2026-10-14.
-- The payload preserves verified source identity and display-clock provenance
-- for each future upsert. Existing earlier records are not retroactively guessed.
-- Signed OIDC main-only Edge endpoint is still the sole caller.

CREATE OR REPLACE FUNCTION public.ft_publish_forebet_canonical(p_rows jsonb, p_run_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public', 'private', 'pg_temp'
AS $function$
DECLARE
  r jsonb; f record; id text; ts timestamptz; ko timestamptz;
  h numeric; d numeric; a numeric; pick text; score text; capture_count integer;
  applied integer := 0; skipped integer := 0;
BEGIN
  IF jsonb_typeof(p_rows) IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_rows) NOT BETWEEN 1 AND 500
     OR coalesce(p_run_id,'') !~ '^[0-9]{6,20}$' THEN
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
      IF coalesce(r->>'avg_goals','') !~ '^[0-9]+(\.[0-9]+)?$' OR (r->>'avg_goals')::numeric NOT BETWEEN 0.01 AND 12 THEN
        RAISE EXCEPTION 'INVALID_FOREBET_AVG_GOALS %',id;
      END IF;
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
    IF (r ? 'prob_over25' OR r ? 'prob_under25' OR r ? 'corner_prob_under95' OR r ? 'corner_prob_over95' OR r ? 'corner_prediction' OR r ? 'corner_predicted_score' OR r ? 'avg_corners') THEN
      IF ts>ko OR coalesce(r->>'forebet_detail_url','') !~ '^https://www[.]forebet[.]com/en/football/matches/[^/?#]+-[0-9]{5,12}$'
      THEN RAISE EXCEPTION 'FOREBET_MARKET_SOURCE_OR_TIME_INVALID %',id; END IF;
    END IF;
    IF (r ? 'prob_over25' OR r ? 'prob_under25') THEN
      IF NOT coalesce((r->>'prob_over25') ~ '^[0-9]{1,3}([.][0-9]+)?$',false)
        OR NOT coalesce((r->>'prob_under25') ~ '^[0-9]{1,3}([.][0-9]+)?$',false)
      THEN RAISE EXCEPTION 'FOREBET_OU_INCOMPLETE %',id; END IF;
      IF (r->>'prob_over25')::numeric NOT BETWEEN 0 AND 100
        OR (r->>'prob_under25')::numeric NOT BETWEEN 0 AND 100
        OR ((r->>'prob_over25')::numeric+(r->>'prob_under25')::numeric) NOT BETWEEN 98 AND 102
        OR coalesce(r->>'prediction_ou25','') NOT IN ('Over','Under')
      THEN RAISE EXCEPTION 'FOREBET_OU_INVALID %',id; END IF;
    END IF;
    IF (r ? 'corner_prob_under95' OR r ? 'corner_prob_over95' OR r ? 'corner_prediction' OR r ? 'corner_predicted_score') THEN
      IF NOT coalesce((r->>'corner_prob_under95') ~ '^[0-9]{1,3}([.][0-9]+)?$',false)
        OR NOT coalesce((r->>'corner_prob_over95') ~ '^[0-9]{1,3}([.][0-9]+)?$',false)
      THEN RAISE EXCEPTION 'FOREBET_CORNERS_INCOMPLETE %',id; END IF;
      IF (r->>'corner_prob_under95')::numeric NOT BETWEEN 0 AND 100
        OR (r->>'corner_prob_over95')::numeric NOT BETWEEN 0 AND 100
        OR ((r->>'corner_prob_under95')::numeric+(r->>'corner_prob_over95')::numeric) NOT BETWEEN 98 AND 102
        OR coalesce(r->>'corner_prediction','') NOT IN ('Over','Under')
        OR NOT coalesce((r->>'corner_predicted_score') ~ '^[0-9]{1,2} *- *[0-9]{1,2}$',false)
      THEN RAISE EXCEPTION 'FOREBET_CORNERS_INVALID %',id; END IF;
    END IF;
    IF r ? 'avg_corners' THEN
      IF NOT coalesce((r->>'avg_corners') ~ '^[0-9]+([.][0-9]+)?$',false)
      THEN RAISE EXCEPTION 'FOREBET_AVG_CORNERS_INVALID %',id; END IF;
      IF (r->>'avg_corners')::numeric NOT BETWEEN 0 AND 30
      THEN RAISE EXCEPTION 'FOREBET_AVG_CORNERS_INVALID %',id; END IF;
    END IF;
    SELECT match_id,home_en,away_en,kickoff_hkt INTO f
      FROM public.active_canonical_fixture_current
      WHERE match_id=id;
    IF NOT FOUND OR ko IS DISTINCT FROM f.kickoff_hkt
      OR trim(lower(coalesce(r->>'canonical_home',''))) IS DISTINCT FROM trim(lower(f.home_en))
      OR trim(lower(coalesce(r->>'canonical_away',''))) IS DISTINCT FROM trim(lower(f.away_en))
      OR NOT EXISTS (SELECT 1 FROM public.matches m WHERE m.canonical_event_id=id)
      -- The Forebet availability ledger is an OUTPUT of verified collection,
      -- never a prerequisite. Prior code made every new FS fixture impossible
      -- to publish: 285/285 linked FS fixtures, zero availability rows.
      OR ko < now()-interval '12 hours' OR ko > now()+interval '15 days' THEN
      RAISE EXCEPTION 'FOREBET_FIXTURE_IDENTITY_MISMATCH %',id;
    END IF;
  END LOOP;
  -- V2: the verified Flashscore parent may exist in public.matches but
  -- not yet in private.matches (the evidence FK points to the latter).
  -- Mirror ONLY this fully validated batch, with independent, fresh FS
  -- identity corroboration. No bulk sync, no fabricated matches.
  INSERT INTO private.matches (
    canonical_event_id,canonical_match_id,kickoff_hkt,status,tournament,
    home_en,away_en,home_zh,away_zh,pools,pool_status,in_play,selling,
    fetched_at,source_updated_at,raw,updated_at
  )
  SELECT DISTINCT ON (m.canonical_event_id)
    m.canonical_event_id,m.canonical_match_id,m.kickoff_hkt,m.status,
    m.tournament,m.home_en,m.away_en,m.home_zh,m.away_zh,m.pools,
    m.pool_status,m.in_play,m.selling,m.fetched_at,m.source_updated_at,
    m.raw,now()
  FROM public.matches m
  JOIN public.flashscore_primary_fixture_current fs
    ON fs.match_id=m.canonical_event_id
    AND fs.provider_identity_status='VERIFIED_IDENTITY'
    AND fs.identity_authority='FLASHSCORE'
    AND fs.kickoff_hkt IS NOT DISTINCT FROM m.kickoff_hkt
    AND lower(trim(fs.home_en))=lower(trim(m.home_en))
    AND lower(trim(fs.away_en))=lower(trim(m.away_en))
    AND fs.fetched_at >= now()-interval '36 hours'
  JOIN (
    SELECT DISTINCT x->>'match_id' AS event_id
    FROM jsonb_array_elements(p_rows) x
  ) ids ON ids.event_id=m.canonical_event_id
  WHERE m.canonical_event_id LIKE 'FS:%'
    AND m.kickoff_hkt BETWEEN now()-interval '12 hours' AND now()+interval '15 days'
  ON CONFLICT(canonical_event_id) DO NOTHING;

  FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
    id:=r->>'match_id';
    ts:=(r->>'captured_at')::timestamptz;
    h:=(r->>'home')::numeric;d:=(r->>'draw')::numeric;a:=(r->>'away')::numeric;
    pick:=r->>'pick';score:=r->>'score';
    INSERT INTO public.forebet_predictions (
      canonical_event_id,fetched_at,forebet_match_date,forebet_kickoff_text,
      forebet_league_short,forebet_home_team,forebet_away_team,
      prob_home,prob_draw,prob_away,prediction_1x2,predicted_score,avg_goals,match_score,
      prediction_ou25,prob_over25,prob_under25,ou_predicted_score,
      corner_prediction,corner_prob_under95,corner_prob_over95,corner_predicted_score,
      avg_corners,forebet_detail_url,raw,updated_at)
    VALUES (
      id,ts,r->>'match_date',r->>'kickoff_text',r->>'league',
      r->>'source_home',r->>'source_away',h,d,a,pick,score,
      (r->>'avg_goals')::numeric,(r->>'match_score')::numeric,
      r->>'prediction_ou25',nullif(r->>'prob_over25','')::numeric,
      nullif(r->>'prob_under25','')::numeric,r->>'ou_predicted_score',
      r->>'corner_prediction',nullif(r->>'corner_prob_under95','')::numeric,
      nullif(r->>'corner_prob_over95','')::numeric,r->>'corner_predicted_score',
      nullif(r->>'avg_corners','')::numeric,r->>'forebet_detail_url',
      jsonb_build_object('source','FOREBET','captured_at',ts,'publication_run',p_run_id,
        'market_source_url',r->>'forebet_detail_url','market_capture_pre_kickoff',ts<=(r->>'kickoff')::timestamptz,
        'identity_method',left(coalesce(r->>'identity_method','UNKNOWN'),120),
        'league_verification',left(coalesce(r->>'league_verification','UNKNOWN'),120),
        'source_event_time',r->>'source_event_time',
        'source_event_time_basis',r->>'source_event_time_basis',
        'source_display_offset_minutes',r->>'source_display_offset_minutes',
        'source_provider','FOREBET','identity_authority','FLASHSCORE'),
      now())
    ON CONFLICT (canonical_event_id) DO UPDATE SET
      fetched_at=excluded.fetched_at,forebet_match_date=excluded.forebet_match_date,
      forebet_kickoff_text=excluded.forebet_kickoff_text,
      forebet_league_short=excluded.forebet_league_short,
      forebet_home_team=excluded.forebet_home_team,forebet_away_team=excluded.forebet_away_team,
      prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
      prediction_1x2=excluded.prediction_1x2,predicted_score=excluded.predicted_score,
      avg_goals=excluded.avg_goals,
      prediction_ou25=excluded.prediction_ou25,
      prob_over25=excluded.prob_over25,prob_under25=excluded.prob_under25,
      ou_predicted_score=excluded.ou_predicted_score,
      corner_prediction=excluded.corner_prediction,
      corner_prob_under95=excluded.corner_prob_under95,
      corner_prob_over95=excluded.corner_prob_over95,
      corner_predicted_score=excluded.corner_predicted_score,avg_corners=excluded.avg_corners,
      forebet_detail_url=coalesce(excluded.forebet_detail_url,public.forebet_predictions.forebet_detail_url),
      match_score=excluded.match_score,raw=excluded.raw,updated_at=now()
    WHERE public.forebet_predictions.fetched_at IS NULL
       OR public.forebet_predictions.fetched_at < excluded.fetched_at;
    IF FOUND THEN
      applied:=applied+1;
      INSERT INTO private.prediction_evidence_current(
        canonical_event_id,source_key,market_key,source_updated_at,
        status,pick,predicted_score,prob_home,prob_draw,prob_away,avg_goals,
        source_count,source_members,confidence,raw,updated_at)
      VALUES(
        id,'FOREBET','1X2',ts,'CURRENT',pick,score,h/100,d/100,a/100,(r->>'avg_goals')::numeric,
        1,ARRAY['FOREBET'],(r->>'match_score')::numeric,
        jsonb_build_object('source','FOREBET','captured_at',ts,'publication_run',p_run_id),now())
      ON CONFLICT(canonical_event_id,source_key,market_key) DO UPDATE SET
        source_updated_at=excluded.source_updated_at,status='CURRENT',
        pick=excluded.pick,predicted_score=excluded.predicted_score,
        prob_home=excluded.prob_home,prob_draw=excluded.prob_draw,prob_away=excluded.prob_away,
        avg_goals=excluded.avg_goals,
        source_count=excluded.source_count,source_members=excluded.source_members,
        confidence=excluded.confidence,raw=excluded.raw,updated_at=now()
      WHERE private.prediction_evidence_current.source_updated_at IS NULL
         OR private.prediction_evidence_current.source_updated_at < excluded.source_updated_at;
      -- Create one ledger row only AFTER the entire batch passed exact
      -- active-canonical, team, kickoff, model, and duplicate-ID validation.
      -- No daily pre-population or fake availability for other fixtures.
      INSERT INTO public.forebet_availability(
        match_id,checked_at,match_date,kickoff_hkt,home_en,away_en,
        source_home_team,source_away_team,source_competition,
        fixture_match_score,state,reason,raw,updated_at)
      VALUES (
        id,ts,r->>'match_date',(r->>'kickoff')::timestamptz,
        r->>'canonical_home',r->>'canonical_away',
        r->>'source_home',r->>'source_away',r->>'source_league',
        (r->>'match_score')::numeric,'MODEL','FOREBET_VERIFIED_CAPTURE',
        jsonb_build_object('publication_run',p_run_id,'captured_at',ts,
          'market_source_url',r->>'source_event_url',
          'capture_verified',true),now())
      ON CONFLICT(match_id) DO UPDATE SET
        checked_at=excluded.checked_at,match_date=excluded.match_date,
        kickoff_hkt=excluded.kickoff_hkt,
        home_en=excluded.home_en,away_en=excluded.away_en,
        source_home_team=excluded.source_home_team,
        source_away_team=excluded.source_away_team,
        source_competition=excluded.source_competition,
        fixture_match_score=excluded.fixture_match_score,
        state='MODEL',reason='FOREBET_VERIFIED_CAPTURE',
        raw=public.forebet_availability.raw||excluded.raw,
        updated_at=now()
      WHERE public.forebet_availability.checked_at IS NULL
         OR public.forebet_availability.checked_at < excluded.checked_at
         OR public.forebet_availability.state IS DISTINCT FROM 'MODEL';
    ELSE
      skipped:=skipped+1;
    END IF;
  END LOOP;
  RETURN jsonb_build_object('accepted',capture_count,'applied',applied,'unchanged',skipped,'run',p_run_id);
END;
$function$
;

-- Scoped archival function access; never grant to anon/authenticated.
GRANT EXECUTE ON FUNCTION private.ft_archive_verified_forebet_event(text) TO service_role;
