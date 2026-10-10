import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";

// No user-visible credential, no CORS, no public publisher.
const jwks = createRemoteJWKSet(new URL("https://token.actions.githubusercontent.com/.well-known/jwks"));
const workflow = "sargesticky-code/football-fast-tracker/.github/workflows/ft-500-spf.yml@refs/heads/main";
const error = (status: number, message: string) =>
  Response.json({ error: message }, { status, headers: { "Cache-Control": "no-store" } });

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return error(405, "METHOD_NOT_ALLOWED");
  const bearer = req.headers.get("authorization") ?? "";
  if (!bearer.startsWith("Bearer ")) return error(401, "NO_GITHUB_IDENTITY");
  let claims: Record<string, unknown>;
  try {
    const verified = await jwtVerify(bearer.slice(7), jwks, {
      issuer: "https://token.actions.githubusercontent.com",
      audience: "fast-tracker-supabase",
      algorithms: ["RS256"],
      clockTolerance: "30s",
    });
    claims = verified.payload;
  } catch {
    return error(401, "UNVERIFIED_GITHUB_IDENTITY");
  }
  if (claims.repository !== "sargesticky-code/football-fast-tracker"
    || claims.ref !== "refs/heads/main"
    || claims.workflow_ref !== workflow
    || !["schedule", "workflow_dispatch"].includes(String(claims.event_name))
    || !/^[0-9]{6,20}$/.test(String(claims.run_id ?? ""))) {
    return error(403, "UNAUTHORIZED_WORKFLOW");
  }
  let body: unknown;
  try {
    const text = await req.text();
    if (text.length > 100_000) return error(413, "PAYLOAD_TOO_LARGE");
    body = JSON.parse(text);
  } catch {
    return error(400, "INVALID_JSON");
  }
  const payload = body as { rows?: unknown; source?: string };
  if (payload?.source !== "CHINA_500_SPF"
      || !Array.isArray(payload.rows) || payload.rows.length < 1 || payload.rows.length > 100) {
    return error(422, "NO_VERIFIED_QUOTES");
  }
  const url = Deno.env.get("SUPABASE_URL");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !serviceKey) return error(503, "MISSING_SERVICE_CONFIG");
  try {
    const result = await fetch(url + "/rest/v1/rpc/ft_publish_500_spf", {
      method: "POST",
      headers: { apikey: serviceKey, authorization: "Bearer " + serviceKey,
        "Content-Type": "application/json", "Cache-Control": "no-store" },
      body: JSON.stringify({ p_rows: payload.rows, p_run_id: String(claims.run_id) }),
      signal: AbortSignal.timeout(15_000),
    });
    if (!result.ok) {
      console.error("FT500_PUBLISH_REJECTED", result.status);
      return error(result.status >= 500 ? 503 : 422, "PUBLISH_REJECTED");
    }
    const confirmation = await result.json();
    return Response.json(confirmation, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return error(503, "PUBLISH_UNAVAILABLE");
  }
});
