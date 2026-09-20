# Fast Tracker App V1 data contract

The app reads a public, read-only Edge Function:

`/functions/v1/app-phase1-feed?hours=24`

The function does not expose a database key. It calls the service-role-only RPC
`public.ft_internal_app_phase1_feed(integer)`, which reads the canonical
`api.phase1_match_intelligence_v` contract.

Rules:
- display window: next 24 hours by default; hard cap 48 hours
- only HKJC `selling=true` matches
- decision output remains validation-gated
- app falls back to the bundled snapshot if the live feed is unavailable
- no browser code receives service-role or secret credentials
