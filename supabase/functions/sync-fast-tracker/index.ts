import { createClient } from "npm:@supabase/supabase-js@2.116.0";
import { parse } from "npm:csv-parse@7.0.2/sync";

const GH = "https://raw.githubusercontent.com/sargesticky-code/football-fast-tracker/main/data";
const LIVE = "https://football-fast-tracker-live-sargesticky-9289.vercel.app/api/live_scores?format=csv";

const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
const modern = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
const adminKey = modern.default || Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
if (!adminKey) throw new Error("No Supabase admin key available");
const db = createClient(supabaseUrl, adminKey, { auth: { persistSession: false } });

const blank = (v: unknown) => v === null || v === undefined || String(v).trim() === "";
const text = (v: unknown) => blank(v) ? null : String(v).trim();
const num = (v: unknown) => {
  if (blank(v)) return null;
  const n = Number(String(v).trim());
  return Number.isFinite(n) ? n : null;
};
const int = (v: unknown) => {
  const n = num(v);
  return n === null ? null : Math.trunc(n);
};
const bool = (v: unknown) => {
  if (blank(v)) return null;
  return ["1","true","yes","y"].includes(String(v).trim().toLowerCase());
};

function ts(v: unknown) {
  if (blank(v)) return null;
  const s = String(v).trim();
  const serial = Number(s);
  if (Number.isFinite(serial) && serial >= 20000 && serial <= 80000) {
    return new Date(Date.UTC(1899, 11, 30) + serial * 86400000 - 8 * 3600000).toISOString();
  }
  if (/Z$|[+-]\d\d:\d\d$/.test(s)) return s;
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s + "T00:00:00+08:00";
  return s.replace(" ", "T") + "+08:00";
}

async function csv(url: string) {
  const sep = url.includes("?") ? "&" : "?";
  const r = await fetch(url + sep + "nocache=" + Date.now(), { headers: { "cache-control": "no-cache" } });
  if (!r.ok) throw new Error(`fetch ${url} failed ${r.status}`);
  const body = (await r.text()).replace(/^\uFEFF/, "");
  return parse(body, { columns: true, skip_empty_lines: true, relax_column_count: true }) as Record<string,string>[];
}

async function upsert(table: string, rows: Record<string,unknown>[], onConflict: string, ignoreDuplicates=false) {
  let total = 0;
  for (let i=0; i<rows.length; i+=300) {
    const chunk = rows.slice(i,i+300);
    const { error } = await db.from(table).upsert(chunk, { onConflict, ignoreDuplicates });
    if (error) throw new Error(`${table}: ${error.message}`);
    total += chunk.length;
  }
  return total;
}

async function hashHex(s: string) {
  const bytes = new TextEncoder().encode(s);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2,"0")).join("");
}

async function authorized(req: Request) {
  const provided = req.headers.get("x-fast-tracker-cron") || "";
  if (!provided) return false;
  const { data, error } = await db.from("system_config")
    .select("value").eq("key","cron_secret_sha256").maybeSingle();
  if (error || !data?.value) return false;
  return (await hashHex(provided)) === data.value;
}

async function ensureStubs(rows: Record<string,string>[], spec: {
  event:string, kickoff?:string, league?:string, home?:string, away?:string, homeZh?:string, awayZh?:string
}) {
  const seen = new Map<string,Record<string,unknown>>();
  for (const r of rows) {
    const event = text(r[spec.event]);
    if (!event || seen.has(event)) continue;
    seen.set(event, {
      hkjc_event_id:event,
      kickoff_hkt:spec.kickoff ? ts(r[spec.kickoff]) : null,
      tournament:spec.league ? text(r[spec.league]) : null,
      home_en:spec.home ? text(r[spec.home]) : null,
      away_en:spec.away ? text(r[spec.away]) : null,
      home_zh:spec.homeZh ? text(r[spec.homeZh]) : null,
      away_zh:spec.awayZh ? text(r[spec.awayZh]) : null,
      status:"HISTORICAL_STUB", selling:false, in_play:false,
      raw:{edge_sync_stub:true}
    });
  }
  return upsert("matches",[...seen.values()],"hkjc_event_id",true);
}

async function syncCurrent() {
  const out: Record<string,number> = {};

  const h = await csv(`${GH}/hkjc_current.csv`);
  const matches = h.filter(r=>r.hkjc_event_id).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id), hkjc_match_id:text(r.match_id),
    kickoff_hkt:ts(r.kickoff_hkt), status:text(r.status), tournament:text(r.tournament),
    home_en:text(r.home_en), away_en:text(r.away_en), home_zh:text(r.home_zh), away_zh:text(r.away_zh),
    pools:text(r.pools), pool_status:text(r.pool_status), in_play:bool(r.in_play), selling:bool(r.selling),
    fetched_at:ts(r.fetched_at_hkt), source_updated_at:ts(r.odds_updated_at), raw:r
  }));
  out.matches = await upsert("matches",matches,"hkjc_event_id");
  out.hkjc_odds = await upsert("hkjc_odds_current",h.filter(r=>r.hkjc_event_id).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id), had_home:num(r.had_home), had_draw:num(r.had_draw), had_away:num(r.had_away),
    hil_line:text(r.hil_line), hil_over:num(r.hil_over), hil_under:num(r.hil_under),
    chl_line:text(r.chl_line), chl_over:num(r.chl_over), chl_under:num(r.chl_under),
    fetched_at:ts(r.fetched_at_hkt), odds_updated_at:ts(r.odds_updated_at), raw:r
  })),"hkjc_event_id");

  const fb = await csv(`${GH}/forebet_current.csv`);
  out.forebet = await upsert("forebet_predictions",fb.filter(r=>r.hkjc_event_id).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id), fetched_at:ts(r.fetched_at_hkt),
    forebet_match_date:text(r.match_date), forebet_kickoff_text:text(r.kickoff_text),
    forebet_league_short:text(r.league_short), forebet_home_team:text(r.home_team), forebet_away_team:text(r.away_team),
    prob_home:num(r.prob_home), prob_draw:num(r.prob_draw), prob_away:num(r.prob_away),
    prediction_1x2:text(r.prediction_1x2), predicted_score:text(r.predicted_score), avg_goals:num(r.avg_goals),
    odds_home:num(r.odds_home), odds_draw:num(r.odds_draw), odds_away:num(r.odds_away),
    prediction_ou25:text(r.prediction_ou25), prob_over25:num(r.prob_over25), prob_under25:num(r.prob_under25),
    odds_over25:num(r.odds_over25), odds_under25:num(r.odds_under25), forebet_detail_url:text(r.forebet_detail_url),
    match_score:num(r.match_score), ou_predicted_score:text(r.ou_predicted_score),
    corner_prediction:text(r.corner_prediction), corner_prob_under95:num(r.corner_prob_under95),
    corner_prob_over95:num(r.corner_prob_over95), corner_predicted_score:text(r.corner_predicted_score),
    avg_corners:num(r.avg_corners), power_home:num(r.power_home), power_away:num(r.power_away),
    power_home_name:text(r.power_home_name), power_away_name:text(r.power_away_name),
    power_source:text(r.power_source), power_updated:ts(r.power_updated),
    power_home_match:bool(r.power_home_match), power_away_match:bool(r.power_away_match), raw:r
  })),"hkjc_event_id");

  const md = await csv(`${GH}/model_current.csv`);
  out.models = await upsert("model_predictions",md.filter(r=>r.hkjc_event_id).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id), fetched_at:ts(r.fetched_at_hkt), home:text(r.home), away:text(r.away),
    model_league:text(r.model_league), model_home_name:text(r.model_home_name), model_away_name:text(r.model_away_name),
    dc_prob_home:num(r.dc_prob_home), dc_prob_draw:num(r.dc_prob_draw), dc_prob_away:num(r.dc_prob_away),
    dc_xg_home:num(r.dc_xg_home), dc_xg_away:num(r.dc_xg_away), dc_prob_over25:num(r.dc_prob_over25),
    pi_prob_home:num(r.pi_prob_home), pi_prob_draw:num(r.pi_prob_draw), pi_prob_away:num(r.pi_prob_away),
    pi_home_rating:num(r.pi_home_rating), pi_away_rating:num(r.pi_away_rating), pi_diff:num(r.pi_diff),
    training_matches:int(r.training_matches), team_match_quality:num(r.team_match_quality),
    quality:text(r.quality), model_source:text(r.model_source), raw:r
  })),"hkjc_event_id");

  const aliases = await csv(`${GH}/team_alias_registry.csv`);
  out.aliases = await upsert("team_aliases",aliases.filter(r=>r.forebet_alias && r.canonical_hkjc_name).map(r=>({
    source:"FOREBET", alias:text(r.forebet_alias), canonical_hkjc_name:text(r.canonical_hkjc_name),
    confidence:num(r.confidence), first_seen_hkt:ts(r.first_seen_hkt), last_seen_hkt:ts(r.last_seen_hkt),
    match_count:int(r.match_count), status:text(r.status), alias_source:text(r.source)
  })),"source,alias");

  for (const [file, table, conflict, mapper] of [
    ["form_current.csv","form_predictions","hkjc_event_id",(r:Record<string,string>)=>({
      hkjc_event_id:text(r.hkjc_event_id), fetched_at:ts(r.fetched_at_hkt), home:text(r.home), away:text(r.away),
      form_prob_home:num(r.form_prob_home), form_prob_draw:num(r.form_prob_draw), form_prob_away:num(r.form_prob_away),
      form_xg_home:num(r.form_xg_home), form_xg_away:num(r.form_xg_away), home_games:int(r.home_games),
      away_games:int(r.away_games), home_venue_games:int(r.home_venue_games), away_venue_games:int(r.away_venue_games),
      quality:text(r.quality), model_source:text(r.model_source), raw:r
    })],
    ["odds_movement.csv","odds_movement_current","hkjc_event_id",(r:Record<string,string>)=>({
      hkjc_event_id:text(r.hkjc_event_id), captured_at:ts(r.captured_at_hkt), kickoff_hkt:ts(r.kickoff_hkt),
      home:text(r.home), away:text(r.away), movement_side:text(r.movement_side), now_odds:num(r.now_odds),
      odds_24h:num(r.odds_24h), move_24h_pp:num(r.move_24h_pp), odds_2h:num(r.odds_2h), move_2h_pp:num(r.move_2h_pp),
      odds_1h:num(r.odds_1h), move_1h_pp:num(r.move_1h_pp), vol_24h_pp:num(r.vol_24h_pp), signal:text(r.signal),
      model_side:text(r.model_side), model_prob:num(r.model_prob), model_alignment:text(r.model_alignment),
      match_confidence:num(r.match_confidence), alert_score:num(r.alert_score), raw:r
    })],
    ["prediction_fallback_current.csv","prediction_fallback_current","hkjc_event_id",(r:Record<string,string>)=>({
      hkjc_event_id:text(r.hkjc_event_id), fetched_at:ts(r.fetched_at_hkt), kickoff_hkt:ts(r.kickoff_hkt),
      hkjc_league:text(r.hkjc_league), home_en:text(r.home_en), away_en:text(r.away_en), source:text(r.source),
      source_competition:text(r.source_competition), source_url:text(r.source_url), recommendation:text(r.recommendation),
      market:text(r.market), match_score:num(r.match_score), status:text(r.status), notes:text(r.notes), raw:r
    })],
    ["bet365_current.csv","bet365_current","hkjc_event_id",(r:Record<string,string>)=>({
      hkjc_event_id:text(r.hkjc_event_id), fetched_at:ts(r.fetched_at_hkt), match_date:text(r.match_date),
      kickoff_hkt:ts(r.kickoff_hkt), league:text(r.league), home:text(r.home), away:text(r.away),
      bet365_home:num(r.bet365_home), bet365_draw:num(r.bet365_draw), bet365_away:num(r.bet365_away),
      bet365_fixture_id:text(r.bet365_fixture_id), match_quality:num(r.match_quality), source:text(r.source), raw:r
    })]
  ] as const) {
    const rows = await csv(`${GH}/${file}`);
    await ensureStubs(rows,{event:"hkjc_event_id",kickoff:"kickoff_hkt",league:"league",home:"home",away:"away"});
    out[table] = await upsert(table,rows.filter(r=>r.hkjc_event_id).map(mapper),conflict);
  }

  const supp = await csv(`${GH}/forebet_supplement_current.csv`);
  await ensureStubs(supp,{event:"hkjc_event_id",kickoff:"kickoff_hkt",league:"hkjc_league",home:"home_en",away:"away_en"});
  out.forebet_supplement = await upsert("forebet_supplement",supp.filter(r=>r.hkjc_event_id).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id), fetched_at:ts(r.fetched_at_hkt), kickoff_hkt:ts(r.kickoff_hkt),
    hkjc_league:text(r.hkjc_league), home_en:text(r.home_en), away_en:text(r.away_en),
    prob_home:num(r.prob_home), prob_draw:num(r.prob_draw), prob_away:num(r.prob_away),
    prediction_1x2:text(r.prediction_1x2), predicted_score:text(r.predicted_score), avg_goals:num(r.avg_goals),
    source_url:text(r.source_url), match_score:num(r.match_score), status:text(r.status), notes:text(r.notes),
    prediction_ou25:text(r.prediction_ou25), prob_over25:num(r.prob_over25), prob_under25:num(r.prob_under25),
    ou_predicted_score:text(r.ou_predicted_score), corner_prediction:text(r.corner_prediction),
    corner_prob_under95:num(r.corner_prob_under95), corner_prob_over95:num(r.corner_prob_over95),
    corner_predicted_score:text(r.corner_predicted_score), avg_corners:num(r.avg_corners), raw:r
  })),"hkjc_event_id");

  const av = await csv(`${GH}/forebet_availability.csv`);
  await ensureStubs(av,{event:"hkjc_event_id",kickoff:"kickoff_hkt",league:"league_zh",home:"home_en",away:"away_en"});
  out.forebet_availability = await upsert("forebet_availability",av.filter(r=>r.hkjc_event_id).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id), checked_at:ts(r.checked_at_hkt), match_date:text(r.match_date),
    kickoff_hkt:ts(r.kickoff_hkt), league_zh:text(r.league_zh), home_en:text(r.home_en), away_en:text(r.away_en),
    state:text(r.state), reason:text(r.reason), raw:r
  })),"hkjc_event_id");

  return out;
}

async function syncLive() {
  const rows = await csv(LIVE);
  await ensureStubs(rows,{event:"hkjc_event_id",kickoff:"kickoff_hkt",league:"league",home:"home_en",away:"away_en"});
  const current = rows.filter(r=>r.hkjc_event_id).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id), updated_at_source:ts(r.updatedAt), kickoff_hkt:ts(r.kickoff_hkt),
    league:text(r.league), home_en:text(r.home_en), away_en:text(r.away_en), live_score:text(r.live_score),
    home_score:int(r.home_score), away_score:int(r.away_score), minute:int(r.minute), match_status:text(r.match_status),
    source:text(r.source), source_match_id:text(r.source_match_id), source_home:text(r.source_home),
    source_away:text(r.source_away), match_confidence:num(r.match_confidence), source_updated_at:ts(r.source_updated_at),
    home_corners:int(r.home_corners), away_corners:int(r.away_corners), total_corners:int(r.total_corners),
    corner_line_ref:text(r.corner_line_ref), corners_to_hi:num(r.corners_to_hi), corner_progress:text(r.corner_progress), raw:r
  }));
  const n = await upsert("live_score_current",current,"hkjc_event_id");
  const history = rows.filter(r=>r.hkjc_event_id && r.updatedAt).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id), captured_at_hkt:ts(r.updatedAt), api_updated_at:ts(r.source_updated_at),
    kickoff_hkt:ts(r.kickoff_hkt), league:text(r.league), home_en:text(r.home_en), away_en:text(r.away_en),
    live_score:text(r.live_score), match_minute:int(r.minute), match_status:text(r.match_status), source:text(r.source),
    source_match_id:text(r.source_match_id), match_confidence:num(r.match_confidence), detail_status:"SCORE_FEED",
    home_corners:int(r.home_corners), away_corners:int(r.away_corners), total_corners:int(r.total_corners),
    corner_line_ref:text(r.corner_line_ref), corner_progress:text(r.corner_progress),
    team_stats:[], events:[], momentum:[], full_capture:false, raw:r
  }));
  const hn = await upsert("live_stats_history",history,"hkjc_event_id,captured_at_hkt",true);
  return { live_score_current:n, live_stats_history:hn };
}

async function syncArchive() {
  const rows = await csv(`${GH}/forebet_archive.csv`);
  await ensureStubs(rows,{
    event:"hkjc_event_id",kickoff:"hkjc_kickoff_hkt",league:"hkjc_league",
    home:"hkjc_home_team",away:"hkjc_away_team",homeZh:"hkjc_home_zh",awayZh:"hkjc_away_zh"
  });
  const n = await upsert("forebet_archive",rows.filter(r=>r.hkjc_event_id && r.captured_at_hkt).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id), captured_at:ts(r.captured_at_hkt), hkjc_league:text(r.hkjc_league),
    hkjc_home_team:text(r.hkjc_home_team), hkjc_away_team:text(r.hkjc_away_team),
    hkjc_home_zh:text(r.hkjc_home_zh), hkjc_away_zh:text(r.hkjc_away_zh),
    hkjc_kickoff_hkt:ts(r.hkjc_kickoff_hkt), prob_home:num(r.prob_home), prob_draw:num(r.prob_draw),
    prob_away:num(r.prob_away), prediction_1x2:text(r.prediction_1x2), predicted_score:text(r.predicted_score),
    avg_goals:num(r.avg_goals), power_home:num(r.power_home), power_away:num(r.power_away),
    power_source:text(r.power_source), power_updated:ts(r.power_updated), prediction_ou25:text(r.prediction_ou25),
    prob_over25:num(r.prob_over25), prob_under25:num(r.prob_under25), ou_predicted_score:text(r.ou_predicted_score),
    corner_prediction:text(r.corner_prediction), corner_prob_under95:num(r.corner_prob_under95),
    corner_prob_over95:num(r.corner_prob_over95), corner_predicted_score:text(r.corner_predicted_score),
    avg_corners:num(r.avg_corners), forebet_detail_url:text(r.forebet_detail_url), raw:r
  })),"hkjc_event_id,captured_at");

  const ev = await csv(`${GH}/evaluation_summary.csv`);
  const en = await upsert("evaluation_summary",ev.filter(r=>r.model).map(r=>({
    model:text(r.model), as_of_hkt:ts(r.as_of_hkt), settled_matches:int(r.settled_matches),
    avg_rps:num(r.avg_rps), avg_brier:num(r.avg_brier), avg_logloss:num(r.avg_logloss), raw:r
  })),"model");
  return { forebet_archive:n, evaluation_summary:en };
}

Deno.serve(async (req) => {
  try {
    if (!(await authorized(req))) return Response.json({ok:false,error:"unauthorized"},{status:401});
    const body = req.method === "POST" ? await req.json().catch(()=>({})) : {};
    const mode = body.mode || "current";
    const started = new Date().toISOString();
    const result = mode === "live" ? await syncLive()
      : mode === "archive" ? await syncArchive()
      : await syncCurrent();

    await db.from("source_health").upsert({
      source:"SUPABASE_SYNC", metric:mode, value_text:JSON.stringify(result),
      status:"PASS", notes:`Edge sync ${mode}`, observed_at:new Date().toISOString(),
      raw:{started_at:started,finished_at:new Date().toISOString()}
    },{onConflict:"source,metric"});

    return Response.json({ok:true,mode,result,started_at:started,finished_at:new Date().toISOString()});
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return Response.json({ok:false,error:message},{status:500});
  }
});
