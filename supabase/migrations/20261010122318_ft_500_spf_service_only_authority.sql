-- Applied to Fast Tracker 2026 production as Supabase migration 20261010122318.
-- Official 500.com China Sports Lottery SPF, service-only evidence.
-- The publisher is invoked solely via GitHub OIDC -> locked Edge Function.
CREATE TABLE IF NOT EXISTS public.ft_500_spf_current (
  match_id text PRIMARY KEY,
  source_event_id text NOT NULL UNIQUE,
  source_matchnum text NOT NULL,
  source_home text NOT NULL,
  source_away text NOT NULL,
  league text NOT NULL DEFAULT 'EPL',
  kickoff_hkt timestamptz NOT NULL,
  home numeric NOT NULL CHECK(home BETWEEN 1.01 AND 100),
  draw numeric NOT NULL CHECK(draw BETWEEN 1.01 AND 100),
  away numeric NOT NULL CHECK(away BETWEEN 1.01 AND 100),
  source_updated_at timestamptz NOT NULL,
  captured_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.ft_500_spf_current ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ft_500_spf_current FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.ft_500_spf_current TO service_role;

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
    IF mid IS NULL OR mid !~ '^[A-Za-z0-9:_-]{2,80}$'
      OR incoming_source_id IS NULL OR incoming_source_id !~ '^[0-9]{5,15}$'
      OR r->>'source_matchnum' !~ '^[0-9]{3,8}$'
      OR r->>'source_league' IS DISTINCT FROM '英格兰超级联赛'
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
         WHERE f.match_id=mid AND f.league='EPL'
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
      'EPL',kickoff,h,d,a,source_updated,captured,now()
    )
    ON CONFLICT (match_id) DO UPDATE SET
      home=EXCLUDED.home,draw=EXCLUDED.draw,away=EXCLUDED.away,
      source_updated_at=EXCLUDED.source_updated_at,
      captured_at=EXCLUDED.captured_at,updated_at=now()
    WHERE existing.source_event_id=EXCLUDED.source_event_id
      AND existing.source_updated_at <= EXCLUDED.source_updated_at
      AND existing.captured_at <= EXCLUDED.captured_at;
    GET DIAGNOSTICS affected=ROW_COUNT;
    written := written+affected;
  END LOOP;
  RETURN jsonb_build_object('source','CHINA_500_SPF','accepted',n,'written',written);
END;
$function$


REVOKE ALL ON FUNCTION public.ft_publish_500_spf(jsonb,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ft_publish_500_spf(jsonb,text) TO service_role;
