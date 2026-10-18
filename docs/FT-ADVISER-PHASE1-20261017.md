# Phase 1 — adviser provisional feed authentication (17 October 2026)

## Scope
Only public, read-only delivery of existing BetClan, SportyTrader, PrimaTips and Statarea **provisional** evidence. No scrapers, thresholds, automatic verification, odds ingestion, or HKJC runtime changes.

## Root cause / fix
The legacy deployed adviser Edge Functions submitted server API keys on both `apikey` and `Authorization: Bearer`. New Supabase `sb_secret_*` server keys are **not JWTs** and must be sent using `apikey` only. Both functions now prefer the `default` key from `SUPABASE_SECRET_KEYS` and support `SUPABASE_SERVICE_ROLE_KEY` as a legacy fallback (Bearer only for legacy JWT credentials). Neither key is returned or logged. `verify_jwt=false` remains unchanged for these two public GET-only functions, which validate RPC response contracts and cap rows.

## Production verification (2026-10-17, after deployments)
- `adviser-extra-provisional-feed` Edge Function v3: HTTP 200, 310 `PROVISIONAL_NOT_VERIFIED` rows, valid existing JSON contract.
- `adviser-provisional-feed` Edge Function v3: HTTP 200, 1 `PROVISIONAL_NOT_VERIFIED` row, valid existing JSON contract.
- Tests made using external unauthenticated GET requests from the project's `pg_net` worker, inspecting `net._http_response` for HTTP status and JSON counts. No credentials were supplied to callers.
- Underlying SQL sources already returned these same row counts; no collection/matching data was rewritten.

## Match identity guardrails
- Neither endpoint promotes a fuzzy `0.3` or `0.4` similarity score into a VERIFIED identity.
- Row status remains `PROVISIONAL_NOT_VERIFIED`.
- Home/away names are retained for BOTH source and canonical match.
- Dedicated verified-only view `public.adviser_prediction_current` returned zero rows at time of testing because recent observations did not pass all freshness and strict exact-match checks. **Do not weaken that view to manufacture coverage.**

## Operations and rollback
- Deployment changes are present in Supabase Edge Functions under the same two slugs; repository copies on this branch are the exact deployed v3 source.
- If provider contract fails, revert to last known good function versions v2 via the Supabase deployment history; avoid database rollback or deleting data.
- Test following subsequent API key rotation by calling both GET routes and checking HTTP 200, JSON source/quality markers, and `rows` array. Zero rows is valid when no eligible upcoming source matches exist; 401/503 is a failure.
- Validate frontend rendering separately; a working feed alone is not evidence that the dashboard page fetches or displays provisional rows.
