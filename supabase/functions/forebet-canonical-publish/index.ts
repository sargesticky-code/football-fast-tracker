import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";

const jwks = createRemoteJWKSet(new URL("https://token.actions.githubusercontent.com/.well-known/jwks"));
const issuer = "https://token.actions.githubusercontent.com";
const audience = "fast-tracker-supabase";
const workflowRef = "sargesticky-code/football-fast-tracker/.github/workflows/supabase_private_ingest.yml@refs/heads/main";

Deno.serve(async (request: Request): Promise<Response> => {
  const response = (code: number, body: Record<string, unknown>) =>
    Response.json(body, { status: code, headers: { "Cache-Control": "no-store" } });
  if (!["POST", "GET"].includes(request.method)) return response(405, { error: "METHOD_NOT_ALLOWED" });
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
  const trustedRepo = claims.repository === "sargesticky-code/football-fast-tracker";
  const main = claims.ref === "refs/heads/main" && claims.workflow_ref === workflowRef;
  const preview = claims.ref === "refs/heads/feat/forebet-v2-20261014" &&
    claims.workflow_ref === "sargesticky-code/football-fast-tracker/.github/workflows/supabase_private_ingest.yml@refs/heads/feat/forebet-v2-20261014";
  if (!trustedRepo || !(main || (request.method === "GET" && preview)) ||
      !["schedule", "workflow_run", "workflow_dispatch", "push"].includes(String(claims.event_name)) ||
      !/^\d{6,20}$/.test(String(claims.run_id ?? ""))) {
    return response(403, { error: "UNAUTHORIZED_WORKFLOW" });
  }

  if (request.method === "GET") {
    // OIDC-only. Read verified, recently observed Flashscore fixtures from DB.
    const url = Deno.env.get("SUPABASE_URL"), secret = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    if (!url || !secret) return response(503, { error:"SERVICE_CONFIGURATION_UNAVAILABLE" });
    const now = Date.now();
    const q = new URLSearchParams({
      select:"match_id,kickoff_hkt,league,home_en,away_en,fetched_at,identity_authority,provider_identity_status",
      identity_authority:"eq.FLASHSCORE",provider_identity_status:"eq.VERIFIED_IDENTITY",
      order:"kickoff_hkt.asc",limit:"350"
    });
    q.append("kickoff_hkt", "gte." + new Date(now-2*3600000).toISOString());
    q.append("kickoff_hkt", "lte." + new Date(now+60*3600000).toISOString());
    try {
      const fetchResult = await fetch(url + "/rest/v1/flashscore_primary_fixture_current?" + q, {
        headers:{apikey:secret,authorization:"Bearer "+secret,accept:"application/json"},
        signal:AbortSignal.timeout(12_000)
      });
      if (!fetchResult.ok) {
        console.error("FOREBET_CANONICAL_READ_FAILED", fetchResult.status);
        return response(503,{error:"CANONICAL_FIXTURES_UNAVAILABLE"});
      }
      const rows = await fetchResult.json();
      if (!Array.isArray(rows) || rows.length>350) return response(503,{error:"INVALID_FIXTURE_RESPONSE"});
      const matches = rows.filter((r:any) =>
        /^FS:[A-Za-z0-9_-]{5,32}$/.test(String(r.match_id||"")) &&
        Boolean(r.home_en && r.away_en && r.kickoff_hkt && r.league) &&
        Number.isFinite(Date.parse(r.fetched_at)) &&
        Date.parse(r.fetched_at)>=now-36*3600000 &&
        Date.parse(r.fetched_at)<=now+60000
      ).map((r:any)=>({
        id:r.match_id,kickoff:r.kickoff_hkt,home:r.home_en,away:r.away_en,
        league:r.league,fetchedAt:r.fetched_at,
        sourceContext:{identityStatus:"EXACT_CANONICAL_PROVIDER_FIXTURE",provider:"FLASHSCORE"}
      }));
      if (matches.length<8) return response(503,{error:"INSUFFICIENT_VERIFIED_FS_FIXTURES",count:matches.length});
      return response(200,{source:"flashscore-verified-canonical-fixtures-v2",
        generatedAt:new Date().toISOString(),matches});
    } catch {
      return response(503,{error:"CANONICAL_FIXTURE_READ_FAILED"});
    }
  }

  // Read-only preview cannot publish predictions.
  if (!main) return response(403,{error:"PREVIEW_READ_ONLY"});

  let body: unknown;
  try {
    const bytes = await request.text();
    if (bytes.length > 450_000) return response(413, { error: "BATCH_TOO_LARGE" });
    body = JSON.parse(bytes);
  } catch {
    return response(400, { error: "INVALID_JSON" });
  }
  // Signed main-only reconciliation for *provisional* one-sided candidates.
  // Never calls verified publication RPC or promotes model/aliases by guess.
  const proposal = body as {source?:string; rows?:unknown; verified_ids?:unknown; complete_dates?:unknown};
  if (proposal?.source === "FOREBET_PROVISIONAL_RECONCILE_V1") {
    if (!Array.isArray(proposal.rows) || proposal.rows.length > 180
      || !Array.isArray(proposal.verified_ids) || proposal.verified_ids.length > 350
      || !Array.isArray(proposal.complete_dates) || proposal.complete_dates.length > 3)
      return response(422,{error:"INVALID_PROVISIONAL_ENVELOPE"});
    const base = Deno.env.get("SUPABASE_URL");
    const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    if (!base || !service) return response(503,{error:"SERVICE_CONFIGURATION_UNAVAILABLE"});
    try {
      const result = await fetch(base+"/rest/v1/rpc/ft_reconcile_forebet_provisional",{
        method:"POST",
        headers:{apikey:service,authorization:"Bearer "+service,
          "content-type":"application/json","cache-control":"no-store"},
        body:JSON.stringify({
          p_rows:proposal.rows,p_verified_ids:proposal.verified_ids,
          p_complete_dates:proposal.complete_dates,p_run_id:String(claims.run_id)
        }),
        signal:AbortSignal.timeout(15_000)
      });
      if (!result.ok) {
        console.error("FOREBET_PROVISIONAL_RECONCILE_RPC_REJECTED",result.status);
        return response(result.status>=500?503:422,{error:"PROVISIONAL_RECONCILE_REJECTED"});
      }
      const reconciled = await result.json();
      return response(200,{source:"FOREBET_PROVISIONAL",...reconciled});
    } catch {
      return response(503,{error:"PROVISIONAL_RECONCILE_UNAVAILABLE"});
    }
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
