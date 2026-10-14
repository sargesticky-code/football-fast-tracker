-- Applied to Supabase project heq... on 2026-10-14.
-- HKJC network collectors and their Actions triggers are retired. Existing
-- canonical Flashscore fixture parent constraints remain REQUIRED; renaming
-- the old constraint label does not weaken or drop the referential check.
-- The only Forebet write path is verified GitHub OIDC -> Edge
-- forebet-canonical-publish -> public.ft_publish_forebet_canonical.
-- Legacy Firecrawl Edge endpoint is a 410 tombstone (version 3).
BEGIN;
REVOKE ALL ON FUNCTION public.ft_ingest_forebet_firecrawl_batch(jsonb,text)
  FROM PUBLIC,anon,authenticated,service_role;
DROP FUNCTION IF EXISTS public.ft_ingest_forebet_firecrawl_batch(jsonb,text) RESTRICT;
ALTER TABLE public.forebet_predictions
  RENAME CONSTRAINT forebet_predictions_hkjc_event_id_fkey
  TO forebet_predictions_canonical_event_id_fkey;
ALTER TABLE public.forebet_availability
  RENAME CONSTRAINT forebet_availability_hkjc_event_id_fkey
  TO forebet_availability_canonical_event_id_fkey;
ALTER TABLE public.forebet_supplement
  RENAME CONSTRAINT forebet_supplement_hkjc_event_id_fkey
  TO forebet_supplement_canonical_event_id_fkey;
COMMIT;
-- Completed production verification:
-- firecrawl SQL RPC removed = true
-- Forebet canonical renamed FK constraints = 3
-- FS-verified recently captured Forebet predictions = 44
-- Active HKJC pg_cron jobs = 0.
-- Do NOT replay this SQL against an already-upgraded environment without
-- checking prior migration state; the FK rename statements are one-time only.
