# BetClan + SportyTrader adviser feed — source capture only

2026-10-14. Scope: two requested prediction providers; neither is a bookmaker.

## Existing structure
- Flashscore remains canonical fixture authority; source capture cannot create matches.
- BetClan has 1X2, O/U 2.5, BTTS and correct-score forecast fields.
- SportyTrader offers expert tips and, on some pages, three-way algorithm probabilities. These differ from team form and odds; absent markets stay null.
- Retired multibetter-v1 already contains a BCL adapter using HKJC targets. Do not restart its disabled job or count BCL and BETCLAN as independent opinions without verifying lineage.
- Source kickoff text is not a proven timezone. Unresolved identity is never auto-promoted.

## Delivered on this feature branch
- Two listing pages per provider and up to 12 detail pages/provider/day, 12-second request timeout, 2 MB HTML cap, 1-second request spacing.
- Normalized forecast records with provenance URL and event ID, null for unavailable fields, and stable forecast hash to deduplicate revisions.
- A private staging table migration, not applied to production.
- One scheduled 09:20 Hong Kong-time diagnostic capture daily AFTER this feature branch is merged, plus unit tests on code pushes.
- The capture writes only a short-retention GitHub Action artifact; no production data, secrets, alias maintenance, or external bookmaker calls.

## Remaining acceptance gates before Dashboard integration
1. Inspect actual live source artifact (at least three real details per provider); ensure selectors and dates match.
2. Confirm verified Flashscore fixture identity via BOTH teams, competition and corroborated time on multiple overlapping events. Never auto-match by names/slug alone.
3. Reconcile BCL lineage, and only then add provider-scoped alias evidence to the existing unified alias registry; do not create a daily alias matching loop.
4. Add a source-only, read-side projection on verified matches with status, market, timestamp, source URL and accurate unknowns. Never treat site reference odds as bookmaker quotes.
5. Retain pre-kickoff versioned snapshots for subsequent settled-match accuracy / Brier score, without double counting correlated models.
6. Test displayed data on desktop/mobile with actual DB and public API, not only mocks.

## Verification
- pip install requests==2.32.5 beautifulsoup4==4.12.3
- python -m unittest discover -s tests -p test_advisor_sources.py -v
- python scripts/capture_advisor_sources.py --provider BOTH --max-details 12

Empty or blocked capture fails closed, with no publish; evidence defaults to /tmp/ft-advisor-captures.json.
