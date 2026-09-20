import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2.116.0";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@5.9.6";

const ISSUER = "https://token.actions.githubusercontent.com";
const AUDIENCE = "fast-tracker-supabase";
const REPOSITORY = "sargesticky-code/football-fast-tracker";
const ALLOWED_REFS = new Set([
  "refs/heads/main",
  "refs/heads/supabase-ingest-v2",
]);
const ALLOWED_PATHS = new Map([
  ["data/hkjc_current.csv", "hkjc_current.csv"],
  ["data/forebet_current.csv", "forebet_current.csv"],
  ["data/model_current.csv", "model_current.csv"],
  ["data/team_alias_registry.csv", "team_alias_registry.csv"],
  ["data/form_current.csv", "form_current.csv"],
  ["data/odds_movement.csv", "odds_movement.csv"],
  ["data/prediction_fallback_current.csv", "prediction_fallback_current.csv"],
  ["data/bet365_current.csv", "bet365_current.csv"],
  ["data/forebet_supplement_current.csv", "forebet_supplement_current.csv"],
  ["data/forebet_availability.csv", "forebet_availability.csv"],
  ["data/forebet_archive.csv", "forebet_archive.csv"],
  ["data/evaluation_summary.csv", "evaluation_summary.csv"],
  ["data/hkjc_live_odds.csv", "hkjc_live_odds.csv"],
  ["data/team_form_summary.csv", "team_form_summary.csv"],
]);
const JWKS = createRemoteJWKSet(new URL(`${ISSUER}/.well-known/jwks`));

function getServerKey() {
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (legacy) return legacy;
  const modern = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (modern) {
    try {
      const parsed = JSON.parse(modern);
      if (parsed?.default) return parsed.default as string;
    } catch (_) {}
  }
  return "";
}

async function sha256Hex(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return Response.json({ ok:false, error:"method_not_allowed" }, { status:405 });
  }

  try {
    const auth = req.headers.get("authorization") ?? "";
    if (!auth.toLowerCase().startsWith("bearer ")) {
      return Response.json({ ok:false, error:"missing_bearer" }, { status:401 });
    }

    const token = auth.slice(7).trim();
    const { payload } = await jwtVerify(token, JWKS, {
      issuer: ISSUER,
      audience: AUDIENCE,
    });

    if (payload.repository !== REPOSITORY) {
      return Response.json({ ok:false, error:"repository_not_allowed" }, { status:403 });
    }
    const visibility = String(payload.repository_visibility ?? "");
    if (!["private","public"].includes(visibility)) {
      return Response.json({ ok:false, error:"repository_visibility_not_allowed", visibility }, { status:403 });
    }
    const ref = String(payload.ref ?? "");
    if (!ALLOWED_REFS.has(ref)) {
      return Response.json({ ok:false, error:"ref_not_allowed", ref }, { status:403 });
    }

    const body = await req.json();
    const path = String(body?.path ?? "");
    const storagePath = ALLOWED_PATHS.get(path);
    if (!storagePath) {
      return Response.json({ ok:false, error:"path_not_allowed", path }, { status:400 });
    }
    const content = typeof body?.content === "string" ? body.content : "";
    if (!content) {
      return Response.json({ ok:false, error:"empty_content" }, { status:400 });
    }
    if (content.length > 4_500_000) {
      return Response.json({ ok:false, error:"content_too_large" }, { status:413 });
    }

    const digest = await sha256Hex(content);
    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const serverKey = getServerKey();
    if (!supabaseUrl || !serverKey) throw new Error("server_config_missing");

    const db = createClient(supabaseUrl, serverKey, {
      auth: { persistSession:false, autoRefreshToken:false },
    });

    const { data: previous } = await db
      .from("source_health")
      .select("value_text")
      .eq("source","GITHUB_OIDC_INGEST")
      .eq("metric",storagePath)
      .maybeSingle();

    if (previous?.value_text === digest) {
      return Response.json({
        ok:true,
        changed:false,
        path,
        storagePath,
        sha256:digest,
        repository:payload.repository,
        ref,
        runId:payload.run_id,
      }, { headers:{ "Cache-Control":"no-store" } });
    }

    const blob = new Blob([content], { type:"text/csv; charset=utf-8" });
    const { error: uploadError } = await db.storage
      .from("fast-tracker-ingest")
      .upload(storagePath, blob, { upsert:true, contentType:"text/csv" });
    if (uploadError) throw new Error(`storage_upload:${uploadError.message}`);

    const { error: healthError } = await db.from("source_health").upsert({
      source:"GITHUB_OIDC_INGEST",
      metric:storagePath,
      value_text:digest,
      status:"PASS",
      notes:"Private GitHub Actions OIDC upload to Supabase Storage",
      observed_at:new Date().toISOString(),
      raw:{
        repository:payload.repository,
        ref,
        workflow:payload.workflow,
        run_id:payload.run_id,
        sha256:digest,
        bytes:new TextEncoder().encode(content).byteLength,
      },
    }, { onConflict:"source,metric" });
    if (healthError) throw new Error(`health_upsert:${healthError.message}`);

    return Response.json({
      ok:true,
      changed:true,
      path,
      storagePath,
      sha256:digest,
      repository:payload.repository,
      ref,
      runId:payload.run_id,
    }, { headers:{ "Cache-Control":"no-store" } });
  } catch (error) {
    console.error(error);
    return Response.json({
      ok:false,
      error:error instanceof Error ? error.message : String(error),
    }, { status:401, headers:{ "Cache-Control":"no-store" } });
  }
});