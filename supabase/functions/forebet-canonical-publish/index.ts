import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";

const jwks = createRemoteJWKSet(new URL("https://token.actions.githubusercontent.com/.well-known/jwks"));
const issuer = "https://token.actions.githubusercontent.com";
const audience = "fast-tracker-supabase";
const workflowRef = "sargesticky-code/football-fast-tracker/.github/workflows/supabase_private_ingest.yml@refs/heads/main";

Deno.serve(async (request: Request): Promise<Response> => {
  const response = (code: number, body: Record<string, unknown>) =>
    Response.json(body, { status: code, headers: { "Cache-Control": "no-store" } });
  if (request.method !== "POST") return response(405, { error: "METHOD_NOT_ALLOWED" });
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) return response(401, { error: "MISSING_IDENTITY" });

  let claims: Record<string, unknown>;
  try {
    const verified = await jwtVerify(authorization.slice(7), jwks, {
      issuer, audience, algorithms: ["RS256"], clockTolerance: "30s",
    });
    claims = verified.payload;
  } catch {
    return response(401, { error: "INVALID_GITHUB_IDENTITY" });
  }
  if (claims.repository !== "sargesticky-code/football-fast-tracker"
      || claims.ref !== "refs/heads/main"
      || claims.workflow_ref !== workflowRef
      || !["schedule", "workflow_run", "workflow_dispatch", "push"].includes(String(claims.event_name))
      || !/^\d{6,20}$/.test(String(claims.run_id ?? ""))) {
    return response(403, { error: "UNAUTHORIZED_WORKFLOW" });
  }

  let body: unknown;
  try {
    const bytes = await request.text();
    if (bytes.length > 450_000) return response(413, { error: "BATCH_TOO_LARGE" });
    body = JSON.parse(bytes);
  } catch {
    return response(400, { error: "INVALID_JSON" });
  }
  const payload = body as { rows?: unknown };
  if (!payload || !Array.isArray(payload.rows) || payload.rows.length === 0 || payload.rows.length > 500)
    return response(422, { error: "INVALID_OR_EMPTY_FOREBET_BATCH" });

  // The RPC runs as service_role and commits only a fully validated, exactly matched batch.
  // This credential never leaves the Edge runtime.
  const url = Deno.env.get("SUPABASE_URL");
  const secret = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !secret) return response(503, { error: "SERVICE_CONFIGURATION_UNAVAILABLE" });
  try {
    const result = await fetch(`${url}/rest/v1/rpc/ft_publish_forebet_canonical`, {
      method: "POST",
      headers: {
        apikey: secret,
        authorization: `Bearer ${secret}`,
        "content-type": "application/json",
        "cache-control": "no-store",
      },
      body: JSON.stringify({ p_rows: payload.rows, p_run_id: String(claims.run_id) }),
      signal: AbortSignal.timeout(15_000),
    });
    if (!result.ok) {
      const fault = await result.text();
      // Do not echo SQL/data or credentials to workflow logs.
      console.error("FOREBET_PUBLISH_RPC_FAILURE", result.status, fault.slice(0, 250));
      return response(result.status >= 500 ? 503 : 422, { error: "PUBLISH_REJECTED", status: result.status });
    }
    const published = await result.json();
    return response(200, { source: "FOREBET", ...published });
  } catch {
    return response(503, { error: "PUBLISH_SERVICE_UNAVAILABLE" });
  }
});
