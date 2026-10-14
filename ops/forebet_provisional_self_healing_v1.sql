-- Forebet provisional one-team associations. This is NOT a source of
-- verified forecast evidence and must never populate forebet_predictions.
-- Only the existing main-only OIDC Edge function may invoke the RPC.
CREATE TABLE IF NOT EXISTS private.forebet_provisional_links (
  canonical_event_id text PRIMARY KEY,
  status text NOT NULL DEFAULT 'PROVISIONAL'
    CHECK (status IN ('PROVISIONAL','PROMOTED','DISCONNECTED','EXPIRED')),
  source_url text NOT NULL,
  source_home text NOT NULL,
  source_away text NOT NULL,
  canonical_home text NOT NULL,
  canonical_away text NOT NULL,
  canonical_league text NOT NULL,
  source_league text NOT NULL,
  verified_side text NOT NULL CHECK (verified_side IN ('HOME','AWAY')),
  kickoff_hkt timestamptz NOT NULL,
  source_clock_utc timestamptz NOT NULL,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  last_run_id text NOT NULL,
  observation_runs integer NOT NULL DEFAULT 1 CHECK (observation_runs>0),
  source_model jsonb NOT NULL,
  disconnect_reason text,
  disconnected_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE private.forebet_provisional_links ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON private.forebet_provisional_links FROM PUBLIC,anon,authenticated;
GRANT USAGE ON SCHEMA private TO service_role;
GRANT SELECT,INSERT,UPDATE ON private.forebet_provisional_links TO service_role;
CREATE UNIQUE INDEX IF NOT EXISTS forebet_one_active_source_url
  ON private.forebet_provisional_links (source_url) WHERE status='PROVISIONAL';
CREATE INDEX IF NOT EXISTS forebet_provisional_review
  ON private.forebet_provisional_links (status,kickoff_hkt);

CREATE TABLE IF NOT EXISTS private.forebet_provisional_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 canonical_event_id text NOT NULL,
 run_id text NOT NULL,
 transition text NOT NULL,
 reason text,
 source_url text,
 logged_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE private.forebet_provisional_audit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON private.forebet_provisional_audit FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,DELETE ON private.forebet_provisional_audit TO service_role;
GRANT USAGE,SELECT ON SEQUENCE private.forebet_provisional_audit_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public.ft_reconcile_forebet_provisional(
 p_rows jsonb,p_verified_ids jsonb,p_complete_dates jsonb,p_run_id text
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER
SET search_path TO pg_catalog,public,private,pg_temp
AS $function$
DECLARE
 r jsonb; x record; fs record;
 v_id text; v_url text; v_status text; v_reason text;
 v_prev private.forebet_provisional_links%ROWTYPE;
 v_provisional integer:=0; v_disconnected integer:=0;
 v_promoted integer:=0; v_expired integer:=0;
 v_same integer:=0; v_collisions integer:=0;
 v_seen integer; v_model jsonb;
BEGIN
 IF jsonb_typeof(p_rows) IS DISTINCT FROM 'array'
  OR jsonb_array_length(p_rows)>180
  OR jsonb_typeof(p_verified_ids) IS DISTINCT FROM 'array'
  OR jsonb_array_length(p_verified_ids)>350
  OR jsonb_typeof(p_complete_dates) IS DISTINCT FROM 'array'
  OR jsonb_array_length(p_complete_dates)>3
  OR coalesce(p_run_id,'') !~ '^[0-9]{6,20}$'
 THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_INVALID_ENVELOPE'; END IF;
 IF (SELECT count(DISTINCT item->>'match_id') FROM jsonb_array_elements(p_rows) item)
       <>jsonb_array_length(p_rows)
   OR (SELECT count(DISTINCT item->>'source_url') FROM jsonb_array_elements(p_rows) item)
       <>jsonb_array_length(p_rows)
 THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_DUPLICATE'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(p_complete_dates) d
           WHERE d !~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}$')
 THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_INVALID_PAGE_DATE'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(p_verified_ids) d
           WHERE d !~ '^FS:[A-Za-z0-9_-]{5,32}$')
 THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_INVALID_VERIFIED_ID'; END IF;

 -- Validate the ENTIRE requested set before mutating any record.
 FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
  v_id:=r->>'match_id'; v_url:=r->>'source_url';
  IF coalesce(v_id,'') !~ '^FS:[A-Za-z0-9_-]{5,32}
   OR coalesce(v_url,'') !~ '^https://www[.]forebet[.]com/en/football/matches/[^/?#]{2,240}-[0-9]{5,12}
   OR r->>'matched_identity' IS DISTINCT FROM 'ONE_SIDE_WITH_CONFIRMED_COMPETITION_AND_UNIQUE_KICKOFF'
   OR coalesce(r->>'one_verified_side','') NOT IN ('HOME','AWAY')
   OR r->>'source_league' IS NULL OR length(r->>'source_league') NOT BETWEEN 1 AND 25
   OR coalesce(r->>'source_home','') = '' OR coalesce(r->>'source_away','') = ''
   OR r ? 'match_score' OR r ? 'identity_verified'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(p_verified_ids) v WHERE v=v_id)
  THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_IDENTITY_INVALID %',left(v_id,50); END IF;
  BEGIN
   IF (r->>'source_clock_utc') IS NULL OR (r->>'kickoff') IS NULL
    OR (r->>'home') IS NULL OR (r->>'draw') IS NULL OR (r->>'away') IS NULL
    OR (r->>'avg_goals') IS NULL
    OR abs(extract(epoch from
        ((r->>'source_clock_utc')::timestamptz - (r->>'kickoff')::timestamptz)))>60
    OR (r->>'kickoff')::timestamptz<=now()
    OR (r->>'kickoff')::timestamptz>now()+interval '60 hours'
    OR (r->>'home')::numeric NOT BETWEEN 0 AND 100
    OR (r->>'draw')::numeric NOT BETWEEN 0 AND 100
    OR (r->>'away')::numeric NOT BETWEEN 0 AND 100
    OR ((r->>'home')::numeric+(r->>'draw')::numeric+(r->>'away')::numeric)
         NOT BETWEEN 98 AND 102
    OR (r->>'avg_goals')::numeric NOT BETWEEN 0.01 AND 12
    OR coalesce(r->>'pick','') NOT IN ('1','X','2')
    OR coalesce(r->>'score','') !~ '^[0-9]{1,2} *- *[0-9]{1,2}$'
   THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_MODEL_INVALID'; END IF;
  EXCEPTION WHEN others THEN
   RAISE EXCEPTION 'FOREBET_PROVISIONAL_MODEL_OR_CLOCK_INVALID %',left(v_id,50);
  END;
  SELECT match_id,home_en,away_en,league,kickoff_hkt INTO fs
  FROM public.flashscore_primary_fixture_current
  WHERE match_id=v_id AND identity_authority='FLASHSCORE'
    AND provider_identity_status='VERIFIED_IDENTITY'
    AND fetched_at>=now()-interval '36 hours';
  IF NOT FOUND
   OR fs.kickoff_hkt IS DISTINCT FROM (r->>'kickoff')::timestamptz
   OR btrim(lower(fs.home_en)) <> btrim(lower(r->>'canonical_home'))
   OR btrim(lower(fs.away_en)) <> btrim(lower(r->>'canonical_away'))
   OR btrim(lower(fs.league)) <> btrim(lower(r->>'canonical_league'))
  THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_CANONICAL_CONFLICT %',left(v_id,50);
  END IF;
 END LOOP;

 -- Independently re-check every currently active candidate against fresh FS
 -- fixture identity, original home-away and time; fail closed on any change.
 FOR x IN SELECT l.* FROM private.forebet_provisional_links l
     WHERE l.status='PROVISIONAL' FOR UPDATE LOOP
  v_reason:=null;
  IF x.kickoff_hkt<=now() OR x.last_seen_at<now()-interval '36 hours'
  THEN v_reason:='EXPIRED_OR_STALE';
  ELSIF NOT EXISTS (
   SELECT 1 FROM public.flashscore_primary_fixture_current fs
   WHERE fs.match_id=x.canonical_event_id
     AND fs.identity_authority='FLASHSCORE'
     AND fs.provider_identity_status='VERIFIED_IDENTITY'
     AND fs.fetched_at>=now()-interval '36 hours'
     AND fs.kickoff_hkt=x.kickoff_hkt
     AND lower(btrim(fs.home_en))=lower(btrim(x.canonical_home))
     AND lower(btrim(fs.away_en))=lower(btrim(x.canonical_away))
     AND lower(btrim(fs.league))=lower(btrim(x.canonical_league))
  ) THEN v_reason:='CANONICAL_IDENTITY_CHANGED';
  END IF;
  IF v_reason IS NOT NULL THEN
   v_status:=CASE WHEN v_reason='EXPIRED_OR_STALE' THEN 'EXPIRED' ELSE 'DISCONNECTED' END;
   UPDATE private.forebet_provisional_links
     SET status=v_status,disconnect_reason=v_reason,
         disconnected_at=now(),updated_at=now()
   WHERE canonical_event_id=x.canonical_event_id;
   INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
   VALUES(x.canonical_event_id,p_run_id,v_status,v_reason,x.source_url);
   IF v_status='EXPIRED' THEN v_expired:=v_expired+1;
   ELSE v_disconnected:=v_disconnected+1; END IF;
  END IF;
 END LOOP;

 -- Strict source verification always wins; never copy a provisional model to
 -- the verified archive, simply mark earlier candidate provenance PROMOTED.
 FOR x IN SELECT canonical_event_id,source_url FROM private.forebet_provisional_links
    WHERE status='PROVISIONAL'
      AND canonical_event_id IN (SELECT value FROM jsonb_array_elements_text(p_verified_ids))
      AND EXISTS (
        SELECT 1 FROM public.forebet_predictions f
        WHERE f.canonical_event_id=l.canonical_event_id
          AND f.fetched_at>=now()-interval '36 hours'
      )
    FOR UPDATE LOOP
    UPDATE private.forebet_provisional_links SET status='PROMOTED',
      disconnect_reason='TWO_SIDED_CANONICAL_VERIFIED',
      disconnected_at=now(),updated_at=now()
    WHERE canonical_event_id=x.canonical_event_id;
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
    VALUES(x.canonical_event_id,p_run_id,'PROMOTED','TWO_SIDED_CANONICAL_VERIFIED',x.source_url);
    v_promoted:=v_promoted+1;
 END LOOP;

 FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
  v_id:=r->>'match_id';v_url:=r->>'source_url';
  SELECT * INTO v_prev FROM private.forebet_provisional_links
      WHERE canonical_event_id=v_id FOR UPDATE;
  IF FOUND AND v_prev.status<>'PROVISIONAL' THEN
    v_collisions:=v_collisions+1;
    CONTINUE; -- never auto-revive a disconnected identity
  END IF;
  IF FOUND AND (v_prev.source_url<>v_url
      OR v_prev.source_home<>r->>'source_home'
      OR v_prev.source_away<>r->>'source_away'
      OR v_prev.kickoff_hkt<>(r->>'kickoff')::timestamptz
      OR v_prev.verified_side<>r->>'one_verified_side') THEN
    UPDATE private.forebet_provisional_links
      SET status='DISCONNECTED',disconnect_reason='SOURCE_IDENTITY_DRIFT',
          disconnected_at=now(),updated_at=now() WHERE canonical_event_id=v_id;
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
      VALUES(v_id,p_run_id,'DISCONNECTED','SOURCE_IDENTITY_DRIFT',v_prev.source_url);
    v_disconnected:=v_disconnected+1;
    CONTINUE;
  END IF;
  IF EXISTS(SELECT 1 FROM private.forebet_provisional_links l
     WHERE l.source_url=v_url AND l.canonical_event_id<>v_id
       AND l.status='PROVISIONAL') THEN
    UPDATE private.forebet_provisional_links
      SET status='DISCONNECTED',disconnect_reason='SOURCE_SHARED_BY_OTHER_CANONICAL',
          disconnected_at=now(),updated_at=now()
      WHERE source_url=v_url AND status='PROVISIONAL';
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
       VALUES(v_id,p_run_id,'DISCONNECTED','SOURCE_SHARED_BY_OTHER_CANONICAL',v_url);
    v_disconnected:=v_disconnected+1;
    CONTINUE;
  END IF;
  v_model:=jsonb_build_object('home',r->'home','draw',r->'draw',
       'away',r->'away','pick',r->>'pick','score',r->>'score',
       'avg_goals',r->'avg_goals','is_verified',false);
  IF FOUND THEN
    UPDATE private.forebet_provisional_links
      SET last_seen_at=now(),last_run_id=p_run_id,
          observation_runs=observation_runs+CASE WHEN last_run_id<>p_run_id THEN 1 ELSE 0 END,
          source_model=v_model,updated_at=now()
     WHERE canonical_event_id=v_id;
    v_same:=v_same+1;
  ELSE
    INSERT INTO private.forebet_provisional_links(
     canonical_event_id,source_url,source_home,source_away,
     canonical_home,canonical_away,canonical_league,source_league,
     verified_side,kickoff_hkt,source_clock_utc,
     first_seen_at,last_seen_at,last_run_id,source_model)
    VALUES(v_id,v_url,r->>'source_home',r->>'source_away',
     r->>'canonical_home',r->>'canonical_away',
     r->>'canonical_league',r->>'source_league',
     r->>'one_verified_side',(r->>'kickoff')::timestamptz,
     (r->>'source_clock_utc')::timestamptz,now(),now(),p_run_id,v_model);
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
     VALUES(v_id,p_run_id,'PROVISIONAL','ONE_SIDE_KNOWN_LEAGUE_EXACT_KICKOFF',v_url);
    v_provisional:=v_provisional+1;
  END IF;
 END LOOP;

 -- Only a fully rendered source date can establish that a previously linked
 -- Forebet row vanished. Partial/unavailable pages NEVER revoke by absence.
 WITH lost AS (
   UPDATE private.forebet_provisional_links l SET status='DISCONNECTED',
     disconnect_reason='NOT_REOBSERVED_ON_COMPLETE_SOURCE_DATE',
     disconnected_at=now(),updated_at=now()
   WHERE l.status='PROVISIONAL' AND l.last_run_id<>p_run_id
     AND to_char(l.kickoff_hkt AT TIME ZONE 'UTC','YYYY-MM-DD')
       IN (SELECT value FROM jsonb_array_elements_text(p_complete_dates))
     AND NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements_text(p_verified_ids) v
       WHERE v=l.canonical_event_id
     )
   RETURNING l.canonical_event_id,l.source_url
 )
 INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
 SELECT canonical_event_id,p_run_id,'DISCONNECTED',
        'NOT_REOBSERVED_ON_COMPLETE_SOURCE_DATE',source_url FROM lost;
 GET DIAGNOSTICS v_seen=ROW_COUNT;
 v_disconnected:=v_disconnected+v_seen;
 -- Bounded audit; no unbounded high-frequency historical duplicate snapshots.
 DELETE FROM private.forebet_provisional_audit WHERE logged_at<now()-interval '30 days';
 RETURN jsonb_build_object('source','FOREBET_PROVISIONAL','run',p_run_id,
    'admitted_new',v_provisional,'rechecked',v_same,
    'disconnected',v_disconnected,'promoted',v_promoted,
    'expired',v_expired,'blocked',v_collisions,
    'currently_provisional',(SELECT count(*) FROM private.forebet_provisional_links
      WHERE status='PROVISIONAL' AND kickoff_hkt>now()
        AND last_seen_at>now()-interval '36 hours'));
END;
$function$;
REVOKE ALL ON FUNCTION public.ft_reconcile_forebet_provisional(jsonb,jsonb,jsonb,text)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ft_reconcile_forebet_provisional(jsonb,jsonb,jsonb,text)
  TO service_role;

-- No anon access: this preview data must not be conflated with canonical
-- predictions by existing models or public 1X2 market views.
CREATE OR REPLACE VIEW public.forebet_provisional_feed_current
WITH (security_invoker=true) AS
SELECT l.canonical_event_id,l.kickoff_hkt,l.canonical_home,l.canonical_away,
       l.canonical_league,l.source_home,l.source_away,l.verified_side,
       l.source_url,l.source_model,l.first_seen_at,l.last_seen_at,
       'PROVISIONAL_ONE_SIDE_NOT_VERIFIED'::text AS advisory_status
FROM private.forebet_provisional_links l
JOIN public.flashscore_primary_fixture_current fs
  ON fs.match_id=l.canonical_event_id
 AND fs.kickoff_hkt=l.kickoff_hkt
 AND fs.identity_authority='FLASHSCORE'
 AND fs.provider_identity_status='VERIFIED_IDENTITY'
 AND lower(btrim(fs.home_en))=lower(btrim(l.canonical_home))
 AND lower(btrim(fs.away_en))=lower(btrim(l.canonical_away))
LEFT JOIN public.forebet_predictions f ON f.canonical_event_id=l.canonical_event_id
WHERE l.status='PROVISIONAL'
 AND l.kickoff_hkt>now() AND l.last_seen_at>now()-interval '36 hours'
 AND f.canonical_event_id IS NULL;
REVOKE ALL ON public.forebet_provisional_feed_current FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.forebet_provisional_feed_current TO service_role;

   OR v_url !~ '^https://www[.]forebet[.]com/en/football/matches/[^/?#]{2,240}-[0-9]{5,12}$'
   OR r->>'matched_identity' IS DISTINCT FROM 'ONE_SIDE_WITH_CONFIRMED_COMPETITION_AND_UNIQUE_KICKOFF'
   OR coalesce(r->>'one_verified_side','') NOT IN ('HOME','AWAY')
   OR r->>'source_league' IS NULL OR length(r->>'source_league') NOT BETWEEN 1 AND 25
   OR coalesce(r->>'source_home','') = '' OR coalesce(r->>'source_away','') = ''
   OR r ? 'match_score' OR r ? 'identity_verified'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(p_verified_ids) v WHERE v=v_id)
  THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_IDENTITY_INVALID %',left(v_id,50); END IF;
  BEGIN
   IF abs(extract(epoch from
        ((r->>'source_clock_utc')::timestamptz - (r->>'kickoff')::timestamptz)))>60
    OR (r->>'kickoff')::timestamptz<=now()
    OR (r->>'kickoff')::timestamptz>now()+interval '60 hours'
    OR (r->>'home')::numeric NOT BETWEEN 0 AND 100
    OR (r->>'draw')::numeric NOT BETWEEN 0 AND 100
    OR (r->>'away')::numeric NOT BETWEEN 0 AND 100
    OR ((r->>'home')::numeric+(r->>'draw')::numeric+(r->>'away')::numeric)
         NOT BETWEEN 98 AND 102
    OR (r->>'avg_goals')::numeric NOT BETWEEN 0.01 AND 12
    OR coalesce(r->>'pick','') NOT IN ('1','X','2')
    OR coalesce(r->>'score','') !~ '^[0-9]{1,2} *- *[0-9]{1,2}$'
   THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_MODEL_INVALID'; END IF;
  EXCEPTION WHEN others THEN
   RAISE EXCEPTION 'FOREBET_PROVISIONAL_MODEL_OR_CLOCK_INVALID %',left(v_id,50);
  END;
  SELECT match_id,home_en,away_en,league,kickoff_hkt INTO fs
  FROM public.flashscore_primary_fixture_current
  WHERE match_id=v_id AND identity_authority='FLASHSCORE'
    AND provider_identity_status='VERIFIED_IDENTITY'
    AND fetched_at>=now()-interval '36 hours';
  IF NOT FOUND
   OR fs.kickoff_hkt IS DISTINCT FROM (r->>'kickoff')::timestamptz
   OR btrim(lower(fs.home_en)) <> btrim(lower(r->>'canonical_home'))
   OR btrim(lower(fs.away_en)) <> btrim(lower(r->>'canonical_away'))
   OR btrim(lower(fs.league)) <> btrim(lower(r->>'canonical_league'))
  THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_CANONICAL_CONFLICT %',left(v_id,50);
  END IF;
 END LOOP;

 -- Independently re-check every currently active candidate against fresh FS
 -- fixture identity, original home-away and time; fail closed on any change.
 FOR x IN SELECT l.* FROM private.forebet_provisional_links l
     WHERE l.status='PROVISIONAL' FOR UPDATE LOOP
  v_reason:=null;
  IF x.kickoff_hkt<=now() OR x.last_seen_at<now()-interval '36 hours'
  THEN v_reason:='EXPIRED_OR_STALE';
  ELSIF NOT EXISTS (
   SELECT 1 FROM public.flashscore_primary_fixture_current fs
   WHERE fs.match_id=x.canonical_event_id
     AND fs.identity_authority='FLASHSCORE'
     AND fs.provider_identity_status='VERIFIED_IDENTITY'
     AND fs.fetched_at>=now()-interval '36 hours'
     AND fs.kickoff_hkt=x.kickoff_hkt
     AND lower(btrim(fs.home_en))=lower(btrim(x.canonical_home))
     AND lower(btrim(fs.away_en))=lower(btrim(x.canonical_away))
     AND lower(btrim(fs.league))=lower(btrim(x.canonical_league))
  ) THEN v_reason:='CANONICAL_IDENTITY_CHANGED';
  END IF;
  IF v_reason IS NOT NULL THEN
   v_status:=CASE WHEN v_reason='EXPIRED_OR_STALE' THEN 'EXPIRED' ELSE 'DISCONNECTED' END;
   UPDATE private.forebet_provisional_links
     SET status=v_status,disconnect_reason=v_reason,
         disconnected_at=now(),updated_at=now()
   WHERE canonical_event_id=x.canonical_event_id;
   INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
   VALUES(x.canonical_event_id,p_run_id,v_status,v_reason,x.source_url);
   IF v_status='EXPIRED' THEN v_expired:=v_expired+1;
   ELSE v_disconnected:=v_disconnected+1; END IF;
  END IF;
 END LOOP;

 -- Strict source verification always wins; never copy a provisional model to
 -- the verified archive, simply mark earlier candidate provenance PROMOTED.
 FOR x IN SELECT canonical_event_id,source_url FROM private.forebet_provisional_links
    WHERE status='PROVISIONAL'
      AND canonical_event_id IN (SELECT value FROM jsonb_array_elements_text(p_verified_ids))
      AND EXISTS (
        SELECT 1 FROM public.forebet_predictions f
        WHERE f.canonical_event_id=l.canonical_event_id
          AND f.fetched_at>=now()-interval '36 hours'
      )
    FOR UPDATE LOOP
    UPDATE private.forebet_provisional_links SET status='PROMOTED',
      disconnect_reason='TWO_SIDED_CANONICAL_VERIFIED',
      disconnected_at=now(),updated_at=now()
    WHERE canonical_event_id=x.canonical_event_id;
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
    VALUES(x.canonical_event_id,p_run_id,'PROMOTED','TWO_SIDED_CANONICAL_VERIFIED',x.source_url);
    v_promoted:=v_promoted+1;
 END LOOP;

 FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
  v_id:=r->>'match_id';v_url:=r->>'source_url';
  SELECT * INTO v_prev FROM private.forebet_provisional_links
      WHERE canonical_event_id=v_id FOR UPDATE;
  IF FOUND AND v_prev.status<>'PROVISIONAL' THEN
    v_collisions:=v_collisions+1;
    CONTINUE; -- never auto-revive a disconnected identity
  END IF;
  IF FOUND AND (v_prev.source_url<>v_url
      OR v_prev.source_home<>r->>'source_home'
      OR v_prev.source_away<>r->>'source_away'
      OR v_prev.kickoff_hkt<>(r->>'kickoff')::timestamptz
      OR v_prev.verified_side<>r->>'one_verified_side') THEN
    UPDATE private.forebet_provisional_links
      SET status='DISCONNECTED',disconnect_reason='SOURCE_IDENTITY_DRIFT',
          disconnected_at=now(),updated_at=now() WHERE canonical_event_id=v_id;
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
      VALUES(v_id,p_run_id,'DISCONNECTED','SOURCE_IDENTITY_DRIFT',v_prev.source_url);
    v_disconnected:=v_disconnected+1;
    CONTINUE;
  END IF;
  IF EXISTS(SELECT 1 FROM private.forebet_provisional_links l
     WHERE l.source_url=v_url AND l.canonical_event_id<>v_id
       AND l.status='PROVISIONAL') THEN
    UPDATE private.forebet_provisional_links
      SET status='DISCONNECTED',disconnect_reason='SOURCE_SHARED_BY_OTHER_CANONICAL',
          disconnected_at=now(),updated_at=now()
      WHERE source_url=v_url AND status='PROVISIONAL';
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
       VALUES(v_id,p_run_id,'DISCONNECTED','SOURCE_SHARED_BY_OTHER_CANONICAL',v_url);
    v_disconnected:=v_disconnected+1;
    CONTINUE;
  END IF;
  v_model:=jsonb_build_object('home',r->'home','draw',r->'draw',
       'away',r->'away','pick',r->>'pick','score',r->>'score',
       'avg_goals',r->'avg_goals','is_verified',false);
  IF FOUND THEN
    UPDATE private.forebet_provisional_links
      SET last_seen_at=now(),last_run_id=p_run_id,
          observation_runs=observation_runs+CASE WHEN last_run_id<>p_run_id THEN 1 ELSE 0 END,
          source_model=v_model,updated_at=now()
     WHERE canonical_event_id=v_id;
    v_same:=v_same+1;
  ELSE
    INSERT INTO private.forebet_provisional_links(
     canonical_event_id,source_url,source_home,source_away,
     canonical_home,canonical_away,canonical_league,source_league,
     verified_side,kickoff_hkt,source_clock_utc,
     first_seen_at,last_seen_at,last_run_id,source_model)
    VALUES(v_id,v_url,r->>'source_home',r->>'source_away',
     r->>'canonical_home',r->>'canonical_away',
     r->>'canonical_league',r->>'source_league',
     r->>'one_verified_side',(r->>'kickoff')::timestamptz,
     (r->>'source_clock_utc')::timestamptz,now(),now(),p_run_id,v_model);
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
     VALUES(v_id,p_run_id,'PROVISIONAL','ONE_SIDE_KNOWN_LEAGUE_EXACT_KICKOFF',v_url);
    v_provisional:=v_provisional+1;
  END IF;
 END LOOP;

 -- Only a fully rendered source date can establish that a previously linked
 -- Forebet row vanished. Partial/unavailable pages NEVER revoke by absence.
 UPDATE private.forebet_provisional_links l SET status='DISCONNECTED',
   disconnect_reason='NOT_REOBSERVED_ON_COMPLETE_SOURCE_DATE',
   disconnected_at=now(),updated_at=now()
 WHERE l.status='PROVISIONAL' AND l.last_run_id<>p_run_id
   AND to_char(l.kickoff_hkt AT TIME ZONE 'UTC','YYYY-MM-DD')
     IN (SELECT value FROM jsonb_array_elements_text(p_complete_dates))
   AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(p_verified_ids) v
      WHERE v=l.canonical_event_id
   );
 GET DIAGNOSTICS v_seen=ROW_COUNT;
 v_disconnected:=v_disconnected+v_seen;
 -- Bounded audit; no unbounded high-frequency historical duplicate snapshots.
 DELETE FROM private.forebet_provisional_audit WHERE logged_at<now()-interval '30 days';
 RETURN jsonb_build_object('source','FOREBET_PROVISIONAL','run',p_run_id,
    'admitted_new',v_provisional,'rechecked',v_same,
    'disconnected',v_disconnected,'promoted',v_promoted,
    'expired',v_expired,'blocked',v_collisions,
    'currently_provisional',(SELECT count(*) FROM private.forebet_provisional_links
      WHERE status='PROVISIONAL' AND kickoff_hkt>now()
        AND last_seen_at>now()-interval '36 hours'));
END;
$function$;
REVOKE ALL ON FUNCTION public.ft_reconcile_forebet_provisional(jsonb,jsonb,jsonb,text)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ft_reconcile_forebet_provisional(jsonb,jsonb,jsonb,text)
  TO service_role;

-- No anon access: this preview data must not be conflated with canonical
-- predictions by existing models or public 1X2 market views.
CREATE OR REPLACE VIEW public.forebet_provisional_feed_current
WITH (security_invoker=true) AS
SELECT l.canonical_event_id,l.kickoff_hkt,l.canonical_home,l.canonical_away,
       l.canonical_league,l.source_home,l.source_away,l.verified_side,
       l.source_url,l.source_model,l.first_seen_at,l.last_seen_at,
       'PROVISIONAL_ONE_SIDE_NOT_VERIFIED'::text AS advisory_status
FROM private.forebet_provisional_links l
JOIN public.flashscore_primary_fixture_current fs
  ON fs.match_id=l.canonical_event_id
 AND fs.kickoff_hkt=l.kickoff_hkt
 AND fs.identity_authority='FLASHSCORE'
 AND fs.provider_identity_status='VERIFIED_IDENTITY'
 AND lower(btrim(fs.home_en))=lower(btrim(l.canonical_home))
 AND lower(btrim(fs.away_en))=lower(btrim(l.canonical_away))
LEFT JOIN public.forebet_predictions f ON f.canonical_event_id=l.canonical_event_id
WHERE l.status='PROVISIONAL'
 AND l.kickoff_hkt>now() AND l.last_seen_at>now()-interval '36 hours'
 AND f.canonical_event_id IS NULL;
REVOKE ALL ON public.forebet_provisional_feed_current FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.forebet_provisional_feed_current TO service_role;

   OR r->>'matched_identity' IS DISTINCT FROM 'ONE_SIDE_WITH_CONFIRMED_COMPETITION_AND_UNIQUE_KICKOFF'
   OR coalesce(r->>'one_verified_side','') NOT IN ('HOME','AWAY')
   OR r->>'source_league' IS NULL OR length(r->>'source_league') NOT BETWEEN 1 AND 25
   OR coalesce(r->>'source_home','') = '' OR coalesce(r->>'source_away','') = ''
   OR r ? 'match_score' OR r ? 'identity_verified'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(p_verified_ids) v WHERE v=v_id)
  THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_IDENTITY_INVALID %',left(v_id,50); END IF;
  BEGIN
   IF abs(extract(epoch from
        ((r->>'source_clock_utc')::timestamptz - (r->>'kickoff')::timestamptz)))>60
    OR (r->>'kickoff')::timestamptz<=now()
    OR (r->>'kickoff')::timestamptz>now()+interval '60 hours'
    OR (r->>'home')::numeric NOT BETWEEN 0 AND 100
    OR (r->>'draw')::numeric NOT BETWEEN 0 AND 100
    OR (r->>'away')::numeric NOT BETWEEN 0 AND 100
    OR ((r->>'home')::numeric+(r->>'draw')::numeric+(r->>'away')::numeric)
         NOT BETWEEN 98 AND 102
    OR (r->>'avg_goals')::numeric NOT BETWEEN 0.01 AND 12
    OR coalesce(r->>'pick','') NOT IN ('1','X','2')
    OR coalesce(r->>'score','') !~ '^[0-9]{1,2} *- *[0-9]{1,2}$'
   THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_MODEL_INVALID'; END IF;
  EXCEPTION WHEN others THEN
   RAISE EXCEPTION 'FOREBET_PROVISIONAL_MODEL_OR_CLOCK_INVALID %',left(v_id,50);
  END;
  SELECT match_id,home_en,away_en,league,kickoff_hkt INTO fs
  FROM public.flashscore_primary_fixture_current
  WHERE match_id=v_id AND identity_authority='FLASHSCORE'
    AND provider_identity_status='VERIFIED_IDENTITY'
    AND fetched_at>=now()-interval '36 hours';
  IF NOT FOUND
   OR fs.kickoff_hkt IS DISTINCT FROM (r->>'kickoff')::timestamptz
   OR btrim(lower(fs.home_en)) <> btrim(lower(r->>'canonical_home'))
   OR btrim(lower(fs.away_en)) <> btrim(lower(r->>'canonical_away'))
   OR btrim(lower(fs.league)) <> btrim(lower(r->>'canonical_league'))
  THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_CANONICAL_CONFLICT %',left(v_id,50);
  END IF;
 END LOOP;

 -- Independently re-check every currently active candidate against fresh FS
 -- fixture identity, original home-away and time; fail closed on any change.
 FOR x IN SELECT l.* FROM private.forebet_provisional_links l
     WHERE l.status='PROVISIONAL' FOR UPDATE LOOP
  v_reason:=null;
  IF x.kickoff_hkt<=now() OR x.last_seen_at<now()-interval '36 hours'
  THEN v_reason:='EXPIRED_OR_STALE';
  ELSIF NOT EXISTS (
   SELECT 1 FROM public.flashscore_primary_fixture_current fs
   WHERE fs.match_id=x.canonical_event_id
     AND fs.identity_authority='FLASHSCORE'
     AND fs.provider_identity_status='VERIFIED_IDENTITY'
     AND fs.fetched_at>=now()-interval '36 hours'
     AND fs.kickoff_hkt=x.kickoff_hkt
     AND lower(btrim(fs.home_en))=lower(btrim(x.canonical_home))
     AND lower(btrim(fs.away_en))=lower(btrim(x.canonical_away))
     AND lower(btrim(fs.league))=lower(btrim(x.canonical_league))
  ) THEN v_reason:='CANONICAL_IDENTITY_CHANGED';
  END IF;
  IF v_reason IS NOT NULL THEN
   v_status:=CASE WHEN v_reason='EXPIRED_OR_STALE' THEN 'EXPIRED' ELSE 'DISCONNECTED' END;
   UPDATE private.forebet_provisional_links
     SET status=v_status,disconnect_reason=v_reason,
         disconnected_at=now(),updated_at=now()
   WHERE canonical_event_id=x.canonical_event_id;
   INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
   VALUES(x.canonical_event_id,p_run_id,v_status,v_reason,x.source_url);
   IF v_status='EXPIRED' THEN v_expired:=v_expired+1;
   ELSE v_disconnected:=v_disconnected+1; END IF;
  END IF;
 END LOOP;

 -- Strict source verification always wins; never copy a provisional model to
 -- the verified archive, simply mark earlier candidate provenance PROMOTED.
 FOR x IN SELECT canonical_event_id,source_url FROM private.forebet_provisional_links
    WHERE status='PROVISIONAL'
      AND canonical_event_id IN (SELECT value FROM jsonb_array_elements_text(p_verified_ids))
      AND EXISTS (
        SELECT 1 FROM public.forebet_predictions f
        WHERE f.canonical_event_id=l.canonical_event_id
          AND f.fetched_at>=now()-interval '36 hours'
      )
    FOR UPDATE LOOP
    UPDATE private.forebet_provisional_links SET status='PROMOTED',
      disconnect_reason='TWO_SIDED_CANONICAL_VERIFIED',
      disconnected_at=now(),updated_at=now()
    WHERE canonical_event_id=x.canonical_event_id;
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
    VALUES(x.canonical_event_id,p_run_id,'PROMOTED','TWO_SIDED_CANONICAL_VERIFIED',x.source_url);
    v_promoted:=v_promoted+1;
 END LOOP;

 FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
  v_id:=r->>'match_id';v_url:=r->>'source_url';
  SELECT * INTO v_prev FROM private.forebet_provisional_links
      WHERE canonical_event_id=v_id FOR UPDATE;
  IF FOUND AND v_prev.status<>'PROVISIONAL' THEN
    v_collisions:=v_collisions+1;
    CONTINUE; -- never auto-revive a disconnected identity
  END IF;
  IF FOUND AND (v_prev.source_url<>v_url
      OR v_prev.source_home<>r->>'source_home'
      OR v_prev.source_away<>r->>'source_away'
      OR v_prev.kickoff_hkt<>(r->>'kickoff')::timestamptz
      OR v_prev.verified_side<>r->>'one_verified_side') THEN
    UPDATE private.forebet_provisional_links
      SET status='DISCONNECTED',disconnect_reason='SOURCE_IDENTITY_DRIFT',
          disconnected_at=now(),updated_at=now() WHERE canonical_event_id=v_id;
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
      VALUES(v_id,p_run_id,'DISCONNECTED','SOURCE_IDENTITY_DRIFT',v_prev.source_url);
    v_disconnected:=v_disconnected+1;
    CONTINUE;
  END IF;
  IF EXISTS(SELECT 1 FROM private.forebet_provisional_links l
     WHERE l.source_url=v_url AND l.canonical_event_id<>v_id
       AND l.status='PROVISIONAL') THEN
    UPDATE private.forebet_provisional_links
      SET status='DISCONNECTED',disconnect_reason='SOURCE_SHARED_BY_OTHER_CANONICAL',
          disconnected_at=now(),updated_at=now()
      WHERE source_url=v_url AND status='PROVISIONAL';
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
       VALUES(v_id,p_run_id,'DISCONNECTED','SOURCE_SHARED_BY_OTHER_CANONICAL',v_url);
    v_disconnected:=v_disconnected+1;
    CONTINUE;
  END IF;
  v_model:=jsonb_build_object('home',r->'home','draw',r->'draw',
       'away',r->'away','pick',r->>'pick','score',r->>'score',
       'avg_goals',r->'avg_goals','is_verified',false);
  IF FOUND THEN
    UPDATE private.forebet_provisional_links
      SET last_seen_at=now(),last_run_id=p_run_id,
          observation_runs=observation_runs+CASE WHEN last_run_id<>p_run_id THEN 1 ELSE 0 END,
          source_model=v_model,updated_at=now()
     WHERE canonical_event_id=v_id;
    v_same:=v_same+1;
  ELSE
    INSERT INTO private.forebet_provisional_links(
     canonical_event_id,source_url,source_home,source_away,
     canonical_home,canonical_away,canonical_league,source_league,
     verified_side,kickoff_hkt,source_clock_utc,
     first_seen_at,last_seen_at,last_run_id,source_model)
    VALUES(v_id,v_url,r->>'source_home',r->>'source_away',
     r->>'canonical_home',r->>'canonical_away',
     r->>'canonical_league',r->>'source_league',
     r->>'one_verified_side',(r->>'kickoff')::timestamptz,
     (r->>'source_clock_utc')::timestamptz,now(),now(),p_run_id,v_model);
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
     VALUES(v_id,p_run_id,'PROVISIONAL','ONE_SIDE_KNOWN_LEAGUE_EXACT_KICKOFF',v_url);
    v_provisional:=v_provisional+1;
  END IF;
 END LOOP;

 -- Only a fully rendered source date can establish that a previously linked
 -- Forebet row vanished. Partial/unavailable pages NEVER revoke by absence.
 UPDATE private.forebet_provisional_links l SET status='DISCONNECTED',
   disconnect_reason='NOT_REOBSERVED_ON_COMPLETE_SOURCE_DATE',
   disconnected_at=now(),updated_at=now()
 WHERE l.status='PROVISIONAL' AND l.last_run_id<>p_run_id
   AND to_char(l.kickoff_hkt AT TIME ZONE 'UTC','YYYY-MM-DD')
     IN (SELECT value FROM jsonb_array_elements_text(p_complete_dates))
   AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(p_verified_ids) v
      WHERE v=l.canonical_event_id
   );
 GET DIAGNOSTICS v_seen=ROW_COUNT;
 v_disconnected:=v_disconnected+v_seen;
 -- Bounded audit; no unbounded high-frequency historical duplicate snapshots.
 DELETE FROM private.forebet_provisional_audit WHERE logged_at<now()-interval '30 days';
 RETURN jsonb_build_object('source','FOREBET_PROVISIONAL','run',p_run_id,
    'admitted_new',v_provisional,'rechecked',v_same,
    'disconnected',v_disconnected,'promoted',v_promoted,
    'expired',v_expired,'blocked',v_collisions,
    'currently_provisional',(SELECT count(*) FROM private.forebet_provisional_links
      WHERE status='PROVISIONAL' AND kickoff_hkt>now()
        AND last_seen_at>now()-interval '36 hours'));
END;
$function$;
REVOKE ALL ON FUNCTION public.ft_reconcile_forebet_provisional(jsonb,jsonb,jsonb,text)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ft_reconcile_forebet_provisional(jsonb,jsonb,jsonb,text)
  TO service_role;

-- No anon access: this preview data must not be conflated with canonical
-- predictions by existing models or public 1X2 market views.
CREATE OR REPLACE VIEW public.forebet_provisional_feed_current
WITH (security_invoker=true) AS
SELECT l.canonical_event_id,l.kickoff_hkt,l.canonical_home,l.canonical_away,
       l.canonical_league,l.source_home,l.source_away,l.verified_side,
       l.source_url,l.source_model,l.first_seen_at,l.last_seen_at,
       'PROVISIONAL_ONE_SIDE_NOT_VERIFIED'::text AS advisory_status
FROM private.forebet_provisional_links l
JOIN public.flashscore_primary_fixture_current fs
  ON fs.match_id=l.canonical_event_id
 AND fs.kickoff_hkt=l.kickoff_hkt
 AND fs.identity_authority='FLASHSCORE'
 AND fs.provider_identity_status='VERIFIED_IDENTITY'
 AND lower(btrim(fs.home_en))=lower(btrim(l.canonical_home))
 AND lower(btrim(fs.away_en))=lower(btrim(l.canonical_away))
LEFT JOIN public.forebet_predictions f ON f.canonical_event_id=l.canonical_event_id
WHERE l.status='PROVISIONAL'
 AND l.kickoff_hkt>now() AND l.last_seen_at>now()-interval '36 hours'
 AND f.canonical_event_id IS NULL;
REVOKE ALL ON public.forebet_provisional_feed_current FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.forebet_provisional_feed_current TO service_role;

   OR v_url !~ '^https://www[.]forebet[.]com/en/football/matches/[^/?#]{2,240}-[0-9]{5,12}$'
   OR r->>'matched_identity' IS DISTINCT FROM 'ONE_SIDE_WITH_CONFIRMED_COMPETITION_AND_UNIQUE_KICKOFF'
   OR coalesce(r->>'one_verified_side','') NOT IN ('HOME','AWAY')
   OR r->>'source_league' IS NULL OR length(r->>'source_league') NOT BETWEEN 1 AND 25
   OR coalesce(r->>'source_home','') = '' OR coalesce(r->>'source_away','') = ''
   OR r ? 'match_score' OR r ? 'identity_verified'
   OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(p_verified_ids) v WHERE v=v_id)
  THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_IDENTITY_INVALID %',left(v_id,50); END IF;
  BEGIN
   IF abs(extract(epoch from
        ((r->>'source_clock_utc')::timestamptz - (r->>'kickoff')::timestamptz)))>60
    OR (r->>'kickoff')::timestamptz<=now()
    OR (r->>'kickoff')::timestamptz>now()+interval '60 hours'
    OR (r->>'home')::numeric NOT BETWEEN 0 AND 100
    OR (r->>'draw')::numeric NOT BETWEEN 0 AND 100
    OR (r->>'away')::numeric NOT BETWEEN 0 AND 100
    OR ((r->>'home')::numeric+(r->>'draw')::numeric+(r->>'away')::numeric)
         NOT BETWEEN 98 AND 102
    OR (r->>'avg_goals')::numeric NOT BETWEEN 0.01 AND 12
    OR coalesce(r->>'pick','') NOT IN ('1','X','2')
    OR coalesce(r->>'score','') !~ '^[0-9]{1,2} *- *[0-9]{1,2}$'
   THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_MODEL_INVALID'; END IF;
  EXCEPTION WHEN others THEN
   RAISE EXCEPTION 'FOREBET_PROVISIONAL_MODEL_OR_CLOCK_INVALID %',left(v_id,50);
  END;
  SELECT match_id,home_en,away_en,league,kickoff_hkt INTO fs
  FROM public.flashscore_primary_fixture_current
  WHERE match_id=v_id AND identity_authority='FLASHSCORE'
    AND provider_identity_status='VERIFIED_IDENTITY'
    AND fetched_at>=now()-interval '36 hours';
  IF NOT FOUND
   OR fs.kickoff_hkt IS DISTINCT FROM (r->>'kickoff')::timestamptz
   OR btrim(lower(fs.home_en)) <> btrim(lower(r->>'canonical_home'))
   OR btrim(lower(fs.away_en)) <> btrim(lower(r->>'canonical_away'))
   OR btrim(lower(fs.league)) <> btrim(lower(r->>'canonical_league'))
  THEN RAISE EXCEPTION 'FOREBET_PROVISIONAL_CANONICAL_CONFLICT %',left(v_id,50);
  END IF;
 END LOOP;

 -- Independently re-check every currently active candidate against fresh FS
 -- fixture identity, original home-away and time; fail closed on any change.
 FOR x IN SELECT l.* FROM private.forebet_provisional_links l
     WHERE l.status='PROVISIONAL' FOR UPDATE LOOP
  v_reason:=null;
  IF x.kickoff_hkt<=now() OR x.last_seen_at<now()-interval '36 hours'
  THEN v_reason:='EXPIRED_OR_STALE';
  ELSIF NOT EXISTS (
   SELECT 1 FROM public.flashscore_primary_fixture_current fs
   WHERE fs.match_id=x.canonical_event_id
     AND fs.identity_authority='FLASHSCORE'
     AND fs.provider_identity_status='VERIFIED_IDENTITY'
     AND fs.fetched_at>=now()-interval '36 hours'
     AND fs.kickoff_hkt=x.kickoff_hkt
     AND lower(btrim(fs.home_en))=lower(btrim(x.canonical_home))
     AND lower(btrim(fs.away_en))=lower(btrim(x.canonical_away))
     AND lower(btrim(fs.league))=lower(btrim(x.canonical_league))
  ) THEN v_reason:='CANONICAL_IDENTITY_CHANGED';
  END IF;
  IF v_reason IS NOT NULL THEN
   v_status:=CASE WHEN v_reason='EXPIRED_OR_STALE' THEN 'EXPIRED' ELSE 'DISCONNECTED' END;
   UPDATE private.forebet_provisional_links
     SET status=v_status,disconnect_reason=v_reason,
         disconnected_at=now(),updated_at=now()
   WHERE canonical_event_id=x.canonical_event_id;
   INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
   VALUES(x.canonical_event_id,p_run_id,v_status,v_reason,x.source_url);
   IF v_status='EXPIRED' THEN v_expired:=v_expired+1;
   ELSE v_disconnected:=v_disconnected+1; END IF;
  END IF;
 END LOOP;

 -- Strict source verification always wins; never copy a provisional model to
 -- the verified archive, simply mark earlier candidate provenance PROMOTED.
 FOR x IN SELECT canonical_event_id,source_url FROM private.forebet_provisional_links
    WHERE status='PROVISIONAL'
      AND canonical_event_id IN (SELECT value FROM jsonb_array_elements_text(p_verified_ids))
      AND EXISTS (
        SELECT 1 FROM public.forebet_predictions f
        WHERE f.canonical_event_id=l.canonical_event_id
          AND f.fetched_at>=now()-interval '36 hours'
      )
    FOR UPDATE LOOP
    UPDATE private.forebet_provisional_links SET status='PROMOTED',
      disconnect_reason='TWO_SIDED_CANONICAL_VERIFIED',
      disconnected_at=now(),updated_at=now()
    WHERE canonical_event_id=x.canonical_event_id;
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
    VALUES(x.canonical_event_id,p_run_id,'PROMOTED','TWO_SIDED_CANONICAL_VERIFIED',x.source_url);
    v_promoted:=v_promoted+1;
 END LOOP;

 FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
  v_id:=r->>'match_id';v_url:=r->>'source_url';
  SELECT * INTO v_prev FROM private.forebet_provisional_links
      WHERE canonical_event_id=v_id FOR UPDATE;
  IF FOUND AND v_prev.status<>'PROVISIONAL' THEN
    v_collisions:=v_collisions+1;
    CONTINUE; -- never auto-revive a disconnected identity
  END IF;
  IF FOUND AND (v_prev.source_url<>v_url
      OR v_prev.source_home<>r->>'source_home'
      OR v_prev.source_away<>r->>'source_away'
      OR v_prev.kickoff_hkt<>(r->>'kickoff')::timestamptz
      OR v_prev.verified_side<>r->>'one_verified_side') THEN
    UPDATE private.forebet_provisional_links
      SET status='DISCONNECTED',disconnect_reason='SOURCE_IDENTITY_DRIFT',
          disconnected_at=now(),updated_at=now() WHERE canonical_event_id=v_id;
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
      VALUES(v_id,p_run_id,'DISCONNECTED','SOURCE_IDENTITY_DRIFT',v_prev.source_url);
    v_disconnected:=v_disconnected+1;
    CONTINUE;
  END IF;
  IF EXISTS(SELECT 1 FROM private.forebet_provisional_links l
     WHERE l.source_url=v_url AND l.canonical_event_id<>v_id
       AND l.status='PROVISIONAL') THEN
    UPDATE private.forebet_provisional_links
      SET status='DISCONNECTED',disconnect_reason='SOURCE_SHARED_BY_OTHER_CANONICAL',
          disconnected_at=now(),updated_at=now()
      WHERE source_url=v_url AND status='PROVISIONAL';
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
       VALUES(v_id,p_run_id,'DISCONNECTED','SOURCE_SHARED_BY_OTHER_CANONICAL',v_url);
    v_disconnected:=v_disconnected+1;
    CONTINUE;
  END IF;
  v_model:=jsonb_build_object('home',r->'home','draw',r->'draw',
       'away',r->'away','pick',r->>'pick','score',r->>'score',
       'avg_goals',r->'avg_goals','is_verified',false);
  IF FOUND THEN
    UPDATE private.forebet_provisional_links
      SET last_seen_at=now(),last_run_id=p_run_id,
          observation_runs=observation_runs+CASE WHEN last_run_id<>p_run_id THEN 1 ELSE 0 END,
          source_model=v_model,updated_at=now()
     WHERE canonical_event_id=v_id;
    v_same:=v_same+1;
  ELSE
    INSERT INTO private.forebet_provisional_links(
     canonical_event_id,source_url,source_home,source_away,
     canonical_home,canonical_away,canonical_league,source_league,
     verified_side,kickoff_hkt,source_clock_utc,
     first_seen_at,last_seen_at,last_run_id,source_model)
    VALUES(v_id,v_url,r->>'source_home',r->>'source_away',
     r->>'canonical_home',r->>'canonical_away',
     r->>'canonical_league',r->>'source_league',
     r->>'one_verified_side',(r->>'kickoff')::timestamptz,
     (r->>'source_clock_utc')::timestamptz,now(),now(),p_run_id,v_model);
    INSERT INTO private.forebet_provisional_audit(canonical_event_id,run_id,transition,reason,source_url)
     VALUES(v_id,p_run_id,'PROVISIONAL','ONE_SIDE_KNOWN_LEAGUE_EXACT_KICKOFF',v_url);
    v_provisional:=v_provisional+1;
  END IF;
 END LOOP;

 -- Only a fully rendered source date can establish that a previously linked
 -- Forebet row vanished. Partial/unavailable pages NEVER revoke by absence.
 UPDATE private.forebet_provisional_links l SET status='DISCONNECTED',
   disconnect_reason='NOT_REOBSERVED_ON_COMPLETE_SOURCE_DATE',
   disconnected_at=now(),updated_at=now()
 WHERE l.status='PROVISIONAL' AND l.last_run_id<>p_run_id
   AND to_char(l.kickoff_hkt AT TIME ZONE 'UTC','YYYY-MM-DD')
     IN (SELECT value FROM jsonb_array_elements_text(p_complete_dates))
   AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(p_verified_ids) v
      WHERE v=l.canonical_event_id
   );
 GET DIAGNOSTICS v_seen=ROW_COUNT;
 v_disconnected:=v_disconnected+v_seen;
 -- Bounded audit; no unbounded high-frequency historical duplicate snapshots.
 DELETE FROM private.forebet_provisional_audit WHERE logged_at<now()-interval '30 days';
 RETURN jsonb_build_object('source','FOREBET_PROVISIONAL','run',p_run_id,
    'admitted_new',v_provisional,'rechecked',v_same,
    'disconnected',v_disconnected,'promoted',v_promoted,
    'expired',v_expired,'blocked',v_collisions,
    'currently_provisional',(SELECT count(*) FROM private.forebet_provisional_links
      WHERE status='PROVISIONAL' AND kickoff_hkt>now()
        AND last_seen_at>now()-interval '36 hours'));
END;
$function$;
REVOKE ALL ON FUNCTION public.ft_reconcile_forebet_provisional(jsonb,jsonb,jsonb,text)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ft_reconcile_forebet_provisional(jsonb,jsonb,jsonb,text)
  TO service_role;

-- No anon access: this preview data must not be conflated with canonical
-- predictions by existing models or public 1X2 market views.
CREATE OR REPLACE VIEW public.forebet_provisional_feed_current
WITH (security_invoker=true) AS
SELECT l.canonical_event_id,l.kickoff_hkt,l.canonical_home,l.canonical_away,
       l.canonical_league,l.source_home,l.source_away,l.verified_side,
       l.source_url,l.source_model,l.first_seen_at,l.last_seen_at,
       'PROVISIONAL_ONE_SIDE_NOT_VERIFIED'::text AS advisory_status
FROM private.forebet_provisional_links l
JOIN public.flashscore_primary_fixture_current fs
  ON fs.match_id=l.canonical_event_id
 AND fs.kickoff_hkt=l.kickoff_hkt
 AND fs.identity_authority='FLASHSCORE'
 AND fs.provider_identity_status='VERIFIED_IDENTITY'
 AND lower(btrim(fs.home_en))=lower(btrim(l.canonical_home))
 AND lower(btrim(fs.away_en))=lower(btrim(l.canonical_away))
LEFT JOIN public.forebet_predictions f ON f.canonical_event_id=l.canonical_event_id
WHERE l.status='PROVISIONAL'
 AND l.kickoff_hkt>now() AND l.last_seen_at>now()-interval '36 hours'
 AND f.canonical_event_id IS NULL;
REVOKE ALL ON public.forebet_provisional_feed_current FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.forebet_provisional_feed_current TO service_role;
