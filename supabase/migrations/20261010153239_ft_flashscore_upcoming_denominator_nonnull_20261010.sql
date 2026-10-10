-- Final cumulative production publisher definition after 20261010153121 and 20261010153239.
-- 20-minute source freshness, min 50, 65% among verified canonical UPCOMING provider cohort,
-- individual 20-minute kickoff identity, exact bet365 provenance and unique IDs stay enforced.
CREATE OR REPLACE FUNCTION private.ft_publish_flashscore_collector_snapshot(p_payload jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO 'private', 'public', 'pg_temp'
AS $function$
DECLARE
  v_captured timestamptz;
  v_total integer;
  v_count integer;
  v_distinct integer;
  v_upcoming integer;
  v_rows jsonb;
  v_existing timestamptz;
  v_result jsonb;
BEGIN
  IF p_payload->>'source' IS DISTINCT FROM 'FLASHSCORE_BET365'
    OR jsonb_typeof(p_payload->'fixtures') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'flashscore_snapshot_untrusted_source_or_shape';
  END IF;
  v_total:=jsonb_array_length(p_payload->'fixtures');
  IF v_total < 50 OR v_total > 1500 THEN
    RAISE EXCEPTION 'flashscore_snapshot_unexpected_count_%',v_total;
  END IF;
  v_captured:=(p_payload->>'captured_at')::timestamptz;
  IF v_captured < now()-interval '20 minutes'
    OR v_captured > now()+interval '1 minute' THEN
    RAISE EXCEPTION 'flashscore_snapshot_expired_or_future_%',v_captured;
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('ft_verified_flashscore_bookmaker_publication'));
  SELECT max(fetched_at) INTO v_existing
  FROM public.bet365_current WHERE source='FLASHSCORE_BET365';
  IF v_existing IS NOT NULL AND v_existing >= v_captured THEN
    RETURN jsonb_build_object('status','UNCHANGED','captured_at',v_captured,
      'latest_committed',v_existing);
  END IF;

  WITH provider AS (
    SELECT value AS item,
      value->>'provider_event_id' AS event_id
    FROM jsonb_array_elements(p_payload->'fixtures')
  ), mapped AS (
    SELECT f.item,f.event_id,
      COALESCE(
        red.target_match_id,
        CASE WHEN sh.match_confidence>=0.94 AND
          sh.identity_status IN ('EXACT_PAIR','VERIFIED_IDENTITY','LOOSE_PAIR',
             'TOKEN_PAIR','MIXED_CONTEXT','MIXED_LOOSE','TOKEN_IDENTITY_MIXED')
          THEN sh.match_id END,
        'FS:'||f.event_id
      ) AS candidate,
      sh.raw->>'AD' AS provider_epoch,
      sh.external_event_id AS shadow_event_id,
      sh.match_confidence,
      red.confidence AS redirect_confidence
    FROM provider f
    LEFT JOIN public.fixture_identity_redirects red
      ON red.source_match_id='FS:'||f.event_id
      AND red.active=true AND red.confidence>=0.94
    LEFT JOIN public.phase15_source_shadow_current sh
      ON sh.source_key='FLASHSCORE' AND sh.external_event_id=f.event_id
  ), identified AS (
    SELECT x.*,m.kickoff_hkt,m.tournament,m.home_en,m.away_en,
      CASE WHEN x.provider_epoch ~ '^[0-9]{10}$'
        THEN to_timestamp(x.provider_epoch::double precision) END AS provider_kickoff
    FROM mapped x
    JOIN public.matches m ON m.hkjc_event_id=x.candidate
  ), safe AS (
    SELECT *,
      (item->'hda'->>'home')::numeric AS home_price,
      (item->'hda'->>'draw')::numeric AS draw_price,
      (item->'hda'->>'away')::numeric AS away_price
    FROM identified
    WHERE event_id ~ '^[a-zA-Z0-9]{6,16}$'
      AND item->>'source'='FLASHSCORE_BET365'
      AND lower(item->>'bookmaker')='bet365'
      AND item->>'captured_at' IS NOT NULL
      AND abs(extract(epoch FROM ((item->>'captured_at')::timestamptz-v_captured))) <= 60
      AND provider_kickoff IS NOT NULL
      AND abs(extract(epoch FROM (kickoff_hkt-provider_kickoff)))<=1200
      AND kickoff_hkt > now()
      AND (item->'hda'->>'home') ~ '^[0-9]+(\.[0-9]+)?$'
      AND (item->'hda'->>'draw') ~ '^[0-9]+(\.[0-9]+)?$'
      AND (item->'hda'->>'away') ~ '^[0-9]+(\.[0-9]+)?$'
  ), approved AS (
    SELECT * FROM safe
    WHERE home_price>1 AND home_price<=1000
      AND draw_price>1 AND draw_price<=1000
      AND away_price>1 AND away_price<=1000
  ), source_upcoming AS (
    -- Snapshot includes started/completed matches; they are not eligible
    -- for publication and must not inflate the acceptance denominator.
    SELECT count(*)::integer n FROM identified WHERE kickoff_hkt>now()
  )
  SELECT count(*)::integer,count(distinct candidate)::integer,
    jsonb_agg(jsonb_build_object(
      'match_id',candidate,
      'fetched_at',v_captured,
      'match_date',to_char(kickoff_hkt AT TIME ZONE 'UTC','YYYY-MM-DD'),
      'kickoff_hkt',kickoff_hkt,
      'league',tournament,
      'home',home_en,'away',away_en,
      'home_odds',home_price,'draw_odds',draw_price,'away_odds',away_price,
      'provider_fixture_id',event_id,
      'match_quality', CASE WHEN redirect_confidence IS NOT NULL
        THEN redirect_confidence WHEN match_confidence IS NOT NULL
        THEN greatest(match_confidence,0.94) ELSE 0.995 END,
      'raw',jsonb_build_object(
        'capture',item,
        'provider_epoch',provider_epoch,
        'publication_mode','DIRECT_DATABASE_VERIFIED_PROVIDER_SNAPSHOT'
      ),
      'updated_at',now()
    )),
    max(source_upcoming.n)
  INTO v_count,v_distinct,v_rows,v_upcoming
  FROM approved CROSS JOIN source_upcoming;

  IF v_count < greatest(50,ceil(coalesce(v_upcoming,0)*0.65)::int)
     OR v_count<>v_distinct OR v_rows IS NULL THEN
    RAISE EXCEPTION 'flashscore_snapshot_identity_gate_failed rows_% provider_total_% upcoming_% distinct_%',
      v_count,v_total,v_upcoming,v_distinct;
  END IF;
  v_result:=public.ft_publish_flashscore_hda_current(
     v_rows,
     jsonb_build_object('publication_mode','DIRECT_DATABASE_VERIFIED_PROVIDER_SNAPSHOT',
       'captured_at',v_captured,'total_provider_rows',v_total,
       'eligible_upcoming_provider_rows',v_upcoming,
       'matched_verified_upcoming_rows',v_count,
       'source_http','RAILWAY_COLLECTOR_SNAPSHOT')
  );
  RETURN v_result || jsonb_build_object(
    'captured_at',v_captured,
    'total_provider_rows',v_total,
    'eligible_upcoming_provider_rows',v_upcoming,
    'verified_upcoming_rows',v_count);
END
$function$
;
