# Phase 2 source adapters

This branch is isolated from the production Google Sheet and Phase 1 / Phase 3 logic.

## GitHub references

- pseudo-r/Public-Sofascore-API — reference implementation for Sofascore event, team, squad, player, manager and lineup endpoints. Its documented TLS/WAF behaviour is the reason Phase 2 pins curl_cffi rather than treating plain requests as reliable.
- probberechts/soccerdata — reference/library for normalized football data access and player/lineup patterns.
- felipeall/transfermarkt-api — reference for Transfermarkt-style player/injury-history structures. Historical injury data is context only and must not be promoted to current availability without independent verification.

## Rules

- Start from current HKJC fixtures; never crawl whole player databases.
- Fail closed on ambiguous team/player identities.
- Official club/league/team sources take precedence for confirmed current facts.
- Store source URL, fetch timestamp, confirmed flag, confidence and raw context for evidence.
- Keep CONFIRMED FACT, reliable report and inference distinct.
- No Phase 1 probabilities, no Phase 3 live conclusions, and no combined betting recommendation.
