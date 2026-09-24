# Phase 2 Layer 5 lifecycle audit

Observed 2026-09-24.

Layer 5 keeps projected and official lineups strictly separate. API-Football remains non-odds enrichment only.

Current mapped lifecycle snapshot: 49 mapped fixtures; 6 official-lineup confirmed; 6 not yet due; 1 recent due without confirmation; 36 historical mappings without confirmed lineup. The 253 confirmed lineup evidence rows cover 6 fixtures / 12 team-sides. Every captured side has 11 starters and 11 formation slots.

Failure classification found a scheduler-boundary issue: a fixture checked around kickoff+5m could be skipped at the next :05/:35 run because a strict 30-minute recheck predicate was a few seconds short of 30 minutes; the following run was outside the +55m window. Phase-2 detail therefore uses a 25-minute minimum recheck guard while retaining the -55m/+10m selection window (equivalent to roughly -10m to +55m around kickoff when read as scheduler observation timing). This preserves a second opportunity without broad crawling and keeps the quota floor at 15.

Lifecycle classes for Layer 5: OFFICIAL_COMPLETE, NOT_YET_DUE, PROVIDER_NOT_PUBLISHED, WINDOW_MISSED, CAPTURE_ERROR. Historical no-lineup mappings are not automatically capture failures; detail_check_count and provider response evidence determine classification.
