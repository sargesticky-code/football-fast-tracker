# Fast Tracker 2026 — App V1

This branch is the isolated mobile-first app track.

## Safety boundary

- Does not modify the existing Google Sheet.
- Does not replace the current production ingestion pipeline.
- App V1 is read-only.
- Decision output remains validation-gated.
- The bundled `data/app_snapshot.json` is a real canonical Phase 1 snapshot used only as a UI fallback.

## Run

```bash
npm install
npm run dev
```

## Next data step

Replace the snapshot adapter in `lib/fast-tracker.js` with the server-only Fast Tracker API contract once the Vercel/Supabase server secret path is connected. Do not expose service-role credentials to the browser.
