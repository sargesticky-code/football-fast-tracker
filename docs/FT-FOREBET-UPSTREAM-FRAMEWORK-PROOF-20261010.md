# Forebet — upstream GitHub scraper framework proof (10 October 2026)

## What was actually reused
Upstream architectural reference: [Alm77ar/Forebet-Scraper](https://github.com/Alm77ar/Forebet-Scraper), which runs a one-time browser-helper service in GitHub Actions and uses Playwright/BeautifulSoup to read Forebet fixtures. That repository does not expose a license through GitHub's repo metadata. This branch **implements original compact code based on the workflow idea** and calls the existing Fast Tracker `scrape_forebet.parse_forebet_rows` — it does **not** import or copy an unlicensed upstream script, Telegram logic, credentials or filesystem.

Branch: `probe/ft-forebet-upstream-framework-20261010` (based on existing unmerged PR40, to preserve its strict Canonical tests).

## Real source evidence
- Prior plain Github-hosted Python and Chromium captures returned HTTP **403** and `Just a moment...`; see `docs/FT-FOREBET-GITHUB-403-20261010.md` on PR40.
- GitHub hosted first helper trial [38056984972](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38056984972) on 2026-10-10: official 1X2 dated page HTTP **200**, ~628 KB, **44 real source rows**, **42 structurally valid H/D/A + predicted-score + avg-goal records**. Source HTML had no access challenge marker. Previous six canonical parser tests also passed.
- Tomorrow trial [38057221422](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38057221422) on 2026-10-11 source page: official HTTP **200**, ~989 KB, 44 source rows, 42 valid model structures.
- The page's real `time[itemprop=startDate][datetime]` gives **date only**, e.g. `2026-10-11`. Displayed clock is a separate `span.date_bah`, e.g. `10/11/2026 1:00 AM`. **This is not an offset-bearing source timestamp.** The strict canonical publisher must not call it UTC without verifying Forebet timezone setting / independent event-time cross-check.
- Browser-assisted bounded scroll trial [38057371666](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38057371666): Chromium HTTP 200, initial 44 rows, expanded 44 after bounded eight scroll/click steps. Browser expansion did not yet yield more fixtures. No credentials, cookies, full HTML or DB writes were persisted.


## Verified full-list and independent time-corroboration breakthrough

- One normal DOM click of the site's observed \`#mrows span[onclick*=ltodrows]\`
  exposes **1,115 fixtures** at once. Serializing the whole HTML exceeds
  the intentional 2MB safety ceiling, so the revised collector reads the
  page DOM locally and extracts only pairs corresponding to the existing
  public Fast Tracker Canonical fixture summary.
- [Live selective run 38058049501](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38058049501)
  correctly loaded all 1,115 and selected **25 source matches** from 258
  current Canonical fixtures, with **25 structurally valid 1X2 probabilities,
  predicted scores and average goals**. Selected results are source-only
  candidates: do not count name match as full identity.
- [Independent clock cohort run 38058207762](https://github.com/sargesticky-code/football-fast-tracker/actions/runs/38058207762)
  compared all 25 exact English team-pair candidates with published
  Canonical UTC kickoffs: **23/23 independently parseable displayed clocks
  agreed to the minute with UTC (0-minute difference), across multiple
  competitions; two displayed times could not be safely parsed**.
  The Forebet HTML \`datetime\` attribute itself is still **date-only**, so
  timestamp provenance must say *source displayed time independently
  corroborated by Canonical clock*, not *Forebet supplied ISO timezone*.
- Example observed only: Liverpool–Manchester City, source
  11 October 2026 15:30 displayed, Canonical UTC 15:30, and Hull–Everton
  13:00 matching its original Canonical 13:00. These are evidence,
  not a forecast of the eventual match results.
- Public disclosure/republishing remains OFF. No OIDC publisher invoked,
  no Supabase mutation, no fixture redirect write, no GitHub cron.
- The source framework uses an upstream open-source **architecture** adapted
  into new project-specific code. Alm77ar's scraper did not expose a
  code license at the time checked; its implementation was not
  copy/pasted. The browser helper dependency is separately MIT licensed.

## Live release restrictions
- This is a one-shot **source-only proof**, not an activated live prediction feed.
- Zero scheduled refreshes; zero database writes; zero modifications to Forebet/Flashscore/500.com production tables or public H/D/A model predictions.
- Only one official page per trial; source size <=2MB; run time 8m max; no external paid proxy, Telegram, API token, new Supabase cron or side database.
- No fixture can be promoted to an existing Canonical ID merely by same date, guessed timezone or fuzzy team name, even if probability/score fields look complete.
- The existing production site is publicly addressable, so private intended use does not itself establish that publishing third-party content publicly is private. Full source syndication should remain gated pending the user's chosen private/access-limited use.

## Next verification
1. Verify Forebet displayed clock's selected timezone with actual DOM, then cross-check several source team pairs against independently timed existing fixtures.
2. Expand all necessary fixtures using actual verified source pagination (not unbounded scrolling).
3. Require unique same-league + home/away + kickoff confirmation and full H/D/A, correct score, average goals; reject anything ambiguous.
4. Only after several exact future fixtures survive, use the already-existing private Forebet publication lane and user-authorized refresh cadence, then verify stored DB -> API -> UI.
