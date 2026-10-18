import "jsr:@supabase/functions-js/edge-runtime.d.ts";

// Read-only, bounded, public-facing display of unverified 0.4 source matches.
// The data is already public football forecast information; private service
// credentials and the private candidate/alias tables remain inaccessible.
const cors = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,OPTIONS",
  "access-control-allow-headers": "content-type",
  "cache-control": "public,max-age=40"
};
Deno.serve(async (request: Request): Promise<Response> => {
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  if (request.method !== "GET") return Response.json({ error: "READ_ONLY" }, { status: 405, headers: cors });
  const url = Deno.env.get("SUPABASE_URL");
  // Prefer the current server-only Supabase secret API key.
  // Modern sb_secret_* keys authenticate via apikey, never Bearer.
  let modernKey: string | undefined;
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
    if (typeof keys?.default === "string") modernKey = keys.default;
  } catch { /* Retain the legacy JWT fallback. */ }
  const secret = modernKey || Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !secret) return Response.json({ error: "SERVICE_UNAVAILABLE" }, { status: 503, headers: cors });
  try {
    const resp = await fetch(url + "/rest/v1/rpc/ft_public_adviser_provisional_candidates", {
      method: "POST",
      headers: {
        apikey: secret,
        ...(secret.startsWith("sb_secret_") ? {} : { authorization: "Bearer " + secret }),
        "content-type": "application/json",
        accept: "application/json",
        "cache-control": "no-store"
      },
      body: "{}",
      signal: AbortSignal.timeout(9_000)
    });
    if (!resp.ok) {
      console.error("PUBLIC_ADVISER_PROVISIONAL_RPC_UNAVAILABLE", resp.status);
      return Response.json({ error: "SOURCE_UNAVAILABLE" }, { status: 503, headers: cors });
    }
    const data = await resp.json();
    if (!["ADVISER_PROVISIONAL_FLASHscore_0_4","ADVISER_PROVISIONAL_FLASHscore_0_3"].includes(data?.source) ||
        data?.quality !== "PROVISIONAL_NOT_VERIFIED" ||
        !Array.isArray(data?.rows) || data.rows.length > 180) {
      return Response.json({ error: "INVALID_PROVISIONAL_CONTRACT" }, { status: 503, headers: cors });
    }
    return Response.json(data, { status: 200, headers: cors });
  } catch {
    return Response.json({ error: "SOURCE_TIMEOUT" }, { status: 503, headers: cors });
  }
});
