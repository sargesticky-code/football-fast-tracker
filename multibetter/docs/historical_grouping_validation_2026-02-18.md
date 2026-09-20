# Multibetter historical grouping validation — 2026-02-18

This validation uses the public historical CSV snapshot from Ezee-Kits/SPORTYBET-AUTO-TRADING-BOT and anchors all matching on that project's Forebet rows.

## Input rows

| Source | Rows |
|---|---:|
| ACC | 60 |
| BCL | 54 |
| FST | 44 |
| FRB / Forebet | 106 |
| PRE | 50 |
| STA | 54 |

One Forebet row contained an invalid TIME value, leaving **105 valid Forebet anchors**.

## Grouping result

| Source count per Forebet fixture | Fixtures |
|---:|---:|
| 1 | 47 |
| 2 | 19 |
| 3 | 9 |
| 4 | 7 |
| 5 | 6 |
| 6 | 17 |

- Fixtures with Forebet + at least one additional source: **58 / 105 = 55.2%**
- Fixtures with 4+ sources: **30 / 105**
- Fixtures with all 6 sources: **17 / 105**
- No ACC/BCL/FST/PRE/STA row was reused across multiple Forebet anchors in this run.

## Per-source match quality

| Source | Matched anchors | Coverage of valid Forebet anchors | Median team-pair similarity | Minimum observed |
|---|---:|---:|---:|---:|
| ACC | 38 | 36.2% | 91.9% | 63.9% |
| BCL | 33 | 31.4% | 90.0% | 63.9% |
| FST | 26 | 24.8% | 93.5% | 63.9% |
| PRE | 31 | 29.5% | 91.2% | 64.4% |
| STA | 39 | 37.1% | 90.0% | 63.9% |

Low-scoring examples were generally real naming variants rather than obvious false matches, for example:

- Forebet `Liverpool (URU) / Ind Medellin` vs source `Liverpool Montevideo / Independiente Medellin`
- Forebet `Qarabag / Newcastle United` vs source `FK Qarabag / Newcastle`
- Forebet `Khemis Zemamra / RSB Berkane` vs source `Renaissance Zemamra / Renaissance Berkane`

Therefore V1 keeps the upstream-style 55% discovery threshold but should treat low-similarity matches as review-grade metadata rather than blindly increasing confidence.

## Six-source fixtures observed

1. 01:30 — 2 de Mayo vs Sporting Cristal
2. 01:30 — Liverpool (URU) vs Ind Medellin
3. 11:00 — Shanghai SIPG vs Ulsan Hyundai
4. 11:00 — Melbourne City vs Gangwon FC
5. 17:00 — Khemis Zemamra vs RSB Berkane
6. 18:00 — Manisa BBSK vs Bandirmaspor
7. 18:00 — Spartak Trnava vs Slovan Bratislava
8. 18:30 — Stellenbosch FC vs Magesi FC
9. 18:45 — Qarabag vs Newcastle United
10. 19:00 — FC Winterthur vs St Gallen
11. 20:00 — Levante vs Villarreal
12. 20:45 — Grimsby Town vs Walsall FC
13. 20:45 — Aberdeen vs Motherwell
14. 21:00 — Olympiacos FC vs Bayer Leverkusen
15. 21:00 — Club Brugge vs Atlético Madrid
16. 21:00 — Bodo/Glimt vs Inter
17. 23:00 — O Higgins vs Bahia

## Example weighted consensus

Using the upstream weights ACC 0.8 / BCL 1.0 / FST 0.9 / FRB 1.4 / PRE 1.1 / STA 1.2:

| Fixture | Sources | H | D | A | O2.5 | U2.5 |
|---|---:|---:|---:|---:|---:|---:|
| 2 de Mayo vs Sporting Cristal | 6 | 33.6 | 37.1 | 29.1 | 39.4 | 60.6 |
| Liverpool (URU) vs Ind Medellin | 6 | 37.6 | 32.5 | 29.8 | 48.3 | 51.7 |
| Shanghai SIPG vs Ulsan Hyundai | 6 | 28.6 | 24.7 | 46.6 | 60.4 | 39.6 |
| Melbourne City vs Gangwon FC | 6 | 30.5 | 38.1 | 31.4 | 45.0 | 55.0 |
| Khemis Zemamra vs RSB Berkane | 6 | 26.3 | 24.9 | 48.6 | 41.5 | 58.5 |
| Manisa BBSK vs Bandirmaspor | 6 | 38.5 | 31.6 | 29.5 | 56.6 | 43.4 |
| Spartak Trnava vs Slovan Bratislava | 6 | 28.6 | 31.2 | 40.2 | 57.1 | 42.9 |
| Stellenbosch FC vs Magesi FC | 6 | 51.8 | 29.0 | 19.1 | 35.1 | 64.9 |
| Qarabag vs Newcastle United | 6 | 21.9 | 22.0 | 56.1 | 58.0 | 42.0 |
| FC Winterthur vs St Gallen | 6 | 19.8 | 21.9 | 58.1 | 68.6 | 31.4 |
| Levante vs Villarreal | 6 | 22.8 | 20.4 | 56.5 | 58.5 | 41.5 |
| Grimsby Town vs Walsall FC | 6 | 47.0 | 27.4 | 25.5 | 52.3 | 47.7 |
| Aberdeen vs Motherwell | 6 | 27.6 | 31.5 | 40.9 | 52.5 | 47.5 |
| Olympiacos FC vs Bayer Leverkusen | 6 | 34.6 | 32.9 | 32.4 | 50.0 | 50.0 |
| Club Brugge vs Atlético Madrid | 6 | 28.8 | 23.8 | 47.3 | 59.0 | 41.0 |

## Conclusion

The approved architecture works on real upstream data:

```text
upstream multi-source matching
        ↓
GitHub Forebet anchor
        ↓
OUR Forebet bridge
        ↓
existing HKJC link
```

The next production milestone is to make this grouping/export repeatable from current source CSVs and then join the grouped Forebet anchor to OUR current Forebet feed.
