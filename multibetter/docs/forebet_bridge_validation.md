# GitHub Forebet -> OUR Forebet bridge validation

## Result

The single-bridge approach is supported by the available repository data.

Sample inspected from the external multi-source project:

- 2026-02-18 Forebet CSV: 106 fixtures / 210 unique team names
- 2026-07-24 Forebet CSV: 175 fixtures / 350 unique team names
- Combined: 552 unique GitHub-Forebet team names

Compared with OUR current Forebet registry/current feed:

- 47 names were present in both observed universes.
- All 47/47 overlapping names matched exactly.
- 0 normalized-only naming differences were found in the overlapping sample.
- 505 GitHub-Forebet names were not present in OUR current registry/feed universe.

The 505 non-overlapping names are **not treated as mismatches**. OUR registry is HKJC-driven and only contains Forebet teams that have been encountered through our fixture pipeline, while the external project scrapes a much wider Forebet universe.

## Architecture implication

Use identity matching by default:

```text
GitHub Forebet home/away
        ↓ exact first
OUR Forebet home/away
        ↓
existing OUR Forebet <-> HKJC bridge
        ↓
HKJC event ID
```

A small exception alias table is only needed if a real same-team naming difference is later observed. Do not pre-build aliases for every source.

## Important limitation

The public external project stores historical sample CSVs rather than a live feed for the current Fast Tracker date. Therefore this validation proves naming compatibility on the overlapping historical sample; it does not prove current fixture coverage.

The production bridge should continue to require compatible date/kickoff/home/away and team-class checks.
