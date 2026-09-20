import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2.116.0";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
};

function num(v: unknown) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

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

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "GET") {
    return Response.json({ error: "method_not_allowed" }, {
      status: 405,
      headers: { ...corsHeaders, "Cache-Control": "no-store" },
    });
  }

  try {
    const url = new URL(req.url);
    const requested = Number(url.searchParams.get("hours") ?? "24");
    const hours = Math.max(1, Math.min(48, Number.isFinite(requested) ? requested : 24));

    const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
    const serverKey = getServerKey();
    if (!supabaseUrl || !serverKey) throw new Error("server_config_missing");

    const db = createClient(supabaseUrl, serverKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });

    const { data, error } = await db.rpc("ft_internal_app_phase1_feed", {
      window_hours: hours,
    });
    if (error) throw new Error(`rpc_error:${error.code ?? "unknown"}:${error.message ?? "unknown"}`);

    const rows = Array.isArray(data) ? data : [];
    const matches = rows.map((r: any) => ({
      id: r.hkjc_event_id,
      kickoff: r.kickoff_hkt,
      status: r.status,
      league: r.tournament,
      home: r.home_en,
      away: r.away_en,
      homeZh: r.home_zh,
      awayZh: r.away_zh,
      inPlay: Boolean(r.in_play),
      odds: { home: num(r.hkjc_home_odds), draw: num(r.hkjc_draw_odds), away: num(r.hkjc_away_odds) },
      market: { home: num(r.hkjc_novig_home), draw: num(r.hkjc_novig_draw), away: num(r.hkjc_novig_away) },
      forebet: r.forebet_home == null ? null : { home: num(r.forebet_home), draw: num(r.forebet_draw), away: num(r.forebet_away) },
      dc: r.dc_home == null ? null : { home: num(r.dc_home), draw: num(r.dc_draw), away: num(r.dc_away) },
      pi: r.pi_home == null ? null : { home: num(r.pi_home), draw: num(r.pi_draw), away: num(r.pi_away) },
      form: r.form_home == null ? null : { home: num(r.form_home), draw: num(r.form_draw), away: num(r.form_away) },
      multi: r.multisource_home == null ? null : {
        home: num(r.multisource_home), draw: num(r.multisource_draw), away: num(r.multisource_away),
        sources: Number(r.multisource_count ?? 0), sourceNames: r.multisource_sources ?? [],
      },
      decision: r.decision,
      decisionMarket: r.decision_market,
      decisionSelection: r.decision_selection,
      decisionEdge: num(r.decision_edge),
      engineVersion: r.decision_engine_version,
      updatedAt: r.data_updated_at,
    }));

    return Response.json({
      generatedAt: new Date().toISOString(),
      source: "supabase-canonical-live",
      windowHours: hours,
      count: matches.length,
      matches,
    }, {
      headers: { ...corsHeaders, "Cache-Control": "public, max-age=30, stale-while-revalidate=120" },
    });
  } catch (error) {
    console.error(error);
    return Response.json({
      error: "feed_unavailable",
      message: error instanceof Error ? error.message : String(error),
    }, {
      status: 503,
      headers: { ...corsHeaders, "Cache-Control": "no-store" },
    });
  }
});
