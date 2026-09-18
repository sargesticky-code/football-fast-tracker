# Fast Tracker Live-Market End Goal

This file is the durable product objective for the Football Fast Tracker project.

## Ultimate objective

The system must not stop at predicting H/D/A or a final score.

It should predict **how the match is expected to develop through time**, then compare that expected match path against the actual live match and the live betting market.

Examples of useful pre-match scenario outputs:

- 0-15 min: which side should control possession, territory and corners
- 0-15 min: probability either side scores
- 16-30 min: expected pressure / shot / corner direction
- Half-time: expected score-state distribution
- 46-60 / 61-75 / 76-FT: expected tactical and scoring state
- Expected possession advantage
- Expected shot / shot-on-target advantage
- Expected corner advantage and corner pace
- Expected game-state transitions after a goal, red card or substitution

The live engine then compares:
1. predicted match path,
2. actual live statistics and events,
3. current HKJC live market prices / lines.

When the deviation creates a material, explainable edge, the system should surface a betting signal for:
- HAD / HDA
- Hi/Lo goals
- Corner Hi/Lo
- other markets only when the source and market are genuinely comparable.

## Market styles to detect

### 1. Scenario deviation / live edge
Example:
- model expected Team A to dominate first 15 minutes,
- live possession, shots, territory and corners confirm the pressure,
- market has not adjusted enough,
- surface the relevant live-market edge.

Or:
- model expected an early goal but live chance creation is weak,
- goal line remains over-populated,
- consider an Under / wait / avoid signal rather than blindly following the pre-match model.

### 2. Crowded-market / neglected-information edge
Identify when public/market pricing is concentrated on an obvious side or Over market while:
- player availability,
- tactical matchup,
- manager style,
- line-up quality,
- pace,
- defensive structure,
- set-piece profile,
- or current live match state
points elsewhere.

This can produce:
- underdog/value HAD opportunities,
- high-confidence favourite opportunities when evidence is unusually aligned,
- Hi/Lo opportunities,
- Corner Hi/Lo opportunities.

## Data priority

Recent tactical and personnel information has higher priority than old team history.

Preferred order:
1. confirmed / probable starting XI
2. individual player recent-season form and role
3. injuries / missing players / substitutions
4. manager identity and playing style
5. current formation and tactical matchup
6. recent team tactical form
7. current-season league/team strength
8. older team history only as a weak fallback

Do not let 2012-era or similarly old historical matches dominate current predictions.
Even 2023 data should be low weight when current player/manager context is available.

## Player features to prioritise

For likely starters and key substitutes:
- minutes / starts
- goals, xG
- assists, xA / chances created
- shots / shots on target
- touches in box where available
- passes / progressive or key passes where available
- tackles / interceptions / duels
- aerial threat
- set-piece role
- goalkeeper saves / goals prevented where available
- recent ratings / recent-match contribution
- position and role
- availability / injury / suspension

## Manager / style features

Capture where available:
- manager identity
- usual formation
- pressing / possession tendency
- direct vs patient build-up
- attacking width
- defensive block
- substitution timing tendencies
- behaviour when leading / drawing / trailing
- corner-generation / corner-concession profile
- early-vs-late scoring tendency

## Model behaviour

- Keep models separate first; do not force agreement.
- Compare Forebet, Dixon-Coles, Pi, APWin, Opta/power, player-context and tactical models by market.
- Only compare models on the same market.
- Conflicts are information, not errors.
- Fail closed when evidence is weak.
- A large numerical edge is not a recommendation by itself.
- Recommendations require both price edge and sufficient evidence quality.

## Live recommendation output

Every live signal should eventually explain:
- market
- current price / line
- model fair price / fair line
- edge
- current minute / match state
- what was expected
- what is actually happening
- which inputs support the signal
- which models disagree
- confidence
- action: BET / SMALL / WAIT / AVOID
- invalidation condition (what would make the signal no longer valid)

## Resource / access discipline

- HKJC is the canonical fixture key.
- Capture only HKJC-targeted matches.
- Prefer one reusable upstream response over one request per statistic.
- Cache aggressively.
- No uncontrolled high-frequency scraping.
- Preserve last-good data on source blocks.
- Stop / back off on 403 / 429.
- Never invent missing player or manager information.
