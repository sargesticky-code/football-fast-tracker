import { createClient } from "npm:@supabase/supabase-js@2.116.0";
import { parse } from "npm:csv-parse@7.0.2/sync";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@5.9.6";

const GH = "https://raw.githubusercontent.com/sargesticky-code/football-fast-tracker/main/data";
const INGEST_BUCKET = "fast-tracker-ingest";
const LIVE = "https://football-fast-tracker-live-sargesticky-9289.vercel.app/api/live_scores?format=csv";
const MULTI = "https://raw.githubusercontent.com/sargesticky-code/football-fast-tracker/multibetter-v1/multibetter/data/multibetter_current.csv";
const HKJC_ENDPOINT = "https://info.cld.hkjc.com/graphql/base/";
const GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com";
const GITHUB_OIDC_AUDIENCE = "fast-tracker-supabase";
const GITHUB_OIDC_REPOSITORY = "sargesticky-code/football-fast-tracker";
const GITHUB_OIDC_REFS = new Set(["refs/heads/main","refs/heads/supabase-ingest-v2"]);
const GITHUB_OIDC_JWKS = createRemoteJWKSet(new URL(`${GITHUB_OIDC_ISSUER}/.well-known/jwks`));
const HKJC_RESULT_QUERY = `
    query matchResults($startDate: String, $endDate: String, $startIndex: Int,$endIndex: Int,$teamId: String) {
      matchNumByDate(startDate: $startDate, endDate: $endDate, teamId: $teamId) {
        total
      }
      matches: matchResult(startDate: $startDate, endDate: $endDate, startIndex: $startIndex,endIndex: $endIndex, teamId: $teamId) {
        id
        status
        frontEndId
        matchDayOfWeek
        matchNumber
        matchDate
        kickOffTime
        sequence
        homeTeam {
          id
          name_en
          name_ch
        }
        awayTeam {
          id
          name_en
          name_ch
        }
        tournament {
          code
          name_en
          name_ch      
        }
        results {
          homeResult
          awayResult
          ttlCornerResult
          resultConfirmType
          payoutConfirmed
          stageId
          resultType
          sequence
        }
        poolInfo {
          payoutRefundPools
          refundPools
          ntsInfo
          entInfo
          definedPools
          ngsInfo {
            str
            name_en
            name_ch
            instNo
          }
          agsInfo {
            str
            name_en
            name_ch
            }
        }
      }
    }
  `;

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

async function csvAsset(file: string) {
  const { data, error } = await db.storage.from(INGEST_BUCKET).download(file);
  if (error || !data) throw new Error(`storage ${file} failed ${error?.message || "missing"}`);
  const body = (await data.text()).replace(/^\uFEFF/, "");
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
  if (provided) {
    const { data, error } = await db.from("system_config")
      .select("value").eq("key","cron_secret_sha256").maybeSingle();
    if (!error && data?.value && (await hashHex(provided)) === data.value) return true;
  }

  const auth = req.headers.get("authorization") || "";
  if (!auth.toLowerCase().startsWith("bearer ")) return false;
  try {
    const token = auth.slice(7).trim();
    const { payload } = await jwtVerify(token, GITHUB_OIDC_JWKS, {
      issuer: GITHUB_OIDC_ISSUER,
      audience: GITHUB_OIDC_AUDIENCE,
    });
    return payload.repository === GITHUB_OIDC_REPOSITORY
      && payload.repository_visibility === "private"
      && GITHUB_OIDC_REFS.has(String(payload.ref || ""));
  } catch (_) {
    return false;
  }
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

  const h = await csvAsset("hkjc_current.csv");
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

  const fb = await csvAsset("forebet_current.csv");
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

  const md = await csvAsset("model_current.csv");
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

  const aliases = await csvAsset("team_alias_registry.csv");
  out.aliases = await upsert("team_aliases",aliases.filter(r=>r.forebet_alias && r.canonical_hkjc_name).map(r=>({
    source:"FOREBET", alias:text(r.forebet_alias), canonical_hkjc_name:text(r.canonical_hkjc_name),
    confidence:num(r.confidence), first_seen_hkt:ts(r.first_seen_hkt), last_seen_hkt:ts(r.last_seen_hkt),
    match_count:int(r.match_count), status:text(r.status), alias_source:text(r.source)
  })),"source,alias");

  const simpleFeeds: Array<[string,string,string,(r:Record<string,string>)=>Record<string,unknown>]> = [
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
  ];
  for (const [file, table, conflict, mapper] of simpleFeeds) {
    const rows = await csvAsset(file);
    await ensureStubs(rows,{event:"hkjc_event_id",kickoff:"kickoff_hkt",league:"league",home:"home",away:"away"});
    out[table] = await upsert(table,rows.filter(r=>r.hkjc_event_id).map(mapper),conflict);
  }

  const supp = await csvAsset("forebet_supplement_current.csv");
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

  const av = await csvAsset("forebet_availability.csv");
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


function list(v: unknown, sep="+") {
  if (blank(v)) return [];
  return String(v).split(sep).map(x => x.trim()).filter(Boolean);
}

async function syncMultiSource() {
  const rows = await csv(MULTI);
  const payload = rows.filter(r=>r.hkjc_event_id).map(r=>({
    hkjc_event_id:text(r.hkjc_event_id),
    built_at:ts(r.built_at),
    external_fixture_id:text(r.external_fixture_id),
    github_forebet_date:text(r.github_forebet_date),
    github_forebet_time:text(r.github_forebet_time),
    github_forebet_league:text(r.github_forebet_league),
    github_forebet_home:text(r.github_forebet_home),
    github_forebet_away:text(r.github_forebet_away),
    home_away_explicit:bool(r.home_away_explicit),
    match_status:text(r.match_status),
    match_reason:text(r.match_reason),
    candidate_count:int(r.candidate_count),
    our_forebet_home:text(r.our_forebet_home),
    our_forebet_away:text(r.our_forebet_away),
    hkjc_home:text(r.hkjc_home),
    hkjc_away:text(r.hkjc_away),
    hkjc_kickoff_hkt:ts(r.hkjc_kickoff_hkt),
    source_count_total:int(r.source_count_total),
    sources_total:list(r.sources_total),
    source_count_consensus:int(r.source_count_consensus),
    sources_consensus:list(r.sources_consensus),
    learned_alias_count:int(r.learned_alias_count),
    learned_aliases:list(r.learned_aliases, ";"),
    consensus_home:num(r.consensus_home),
    consensus_draw:num(r.consensus_draw),
    consensus_away:num(r.consensus_away),
    consensus_over25:num(r.consensus_over25),
    consensus_under25:num(r.consensus_under25),
    consensus_btts_yes:num(r.consensus_btts_yes),
    consensus_btts_no:num(r.consensus_btts_no),
    raw:r
  }));
  const { data, error } = await db.rpc("ft_internal_upsert_multisource", { payload });
  if (error) throw new Error("multisource: " + error.message);
  return { rows: payload.length, upserted: data };
}

async function refreshCanonicalCore() {
  const { data, error } = await db.rpc("ft_internal_refresh_phase1_core");
  if (error) throw new Error("canonical core: " + error.message);
  return data;
}


function hkjcDate(daysBack=0) {
  const d = new Date(Date.now() + 8*3600000 - daysBack*86400000);
  const y=d.getUTCFullYear();
  const m=String(d.getUTCMonth()+1).padStart(2,"0");
  const day=String(d.getUTCDate()).padStart(2,"0");
  return `${y}${m}${day}`;
}

async function hkjcGql(query: string, variables: Record<string,unknown>) {
  const r = await fetch(HKJC_ENDPOINT, {
    method:"POST",
    headers:{
      "Content-Type":"application/json",
      "Origin":"https://bet.hkjc.com",
      "Referer":"https://bet.hkjc.com/",
      "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    },
    body:JSON.stringify({query,variables})
  });
  if(!r.ok) throw new Error(`HKJC result HTTP ${r.status}`);
  const body=await r.json();
  if(body.errors?.length) throw new Error("HKJC result GraphQL: "+body.errors.map((e:any)=>e.message||"?").join("; "));
  return body.data || {};
}

async function syncResultsDirect(daysBack=5) {
  const startDate=hkjcDate(daysBack);
  const endDate=hkjcDate(0);

  const first=await hkjcGql(HKJC_RESULT_QUERY,{
    startDate,endDate,startIndex:1,endIndex:20,teamId:null
  });
  const total=Number(first.matchNumByDate?.total||0);
  const matches:any[]=[...(first.matches||[])];

  const starts:number[]=[];
  for(let i=21;i<=total;i+=20) starts.push(i);

  const concurrency=4;
  for(let i=0;i<starts.length;i+=concurrency) {
    const batchStarts=starts.slice(i,i+concurrency);
    const pages=await Promise.all(batchStarts.map(async (idx)=>{
      const data=await hkjcGql(HKJC_RESULT_QUERY,{
        startDate,endDate,startIndex:idx,endIndex:Math.min(idx+19,total),teamId:null
      });
      return data.matches || [];
    }));
    for(const page of pages) matches.push(...page);
  }

  const fetched=new Date().toISOString();
  const rows=matches.flatMap((match:any)=>{
    const ft=(match.results||[]).find((x:any)=>Number(x.resultType)===1 && Number(x.stageId)===5);
    if(!ft) return [];
    const hg=Number(ft.homeResult), ag=Number(ft.awayResult);
    if(!Number.isInteger(hg)||!Number.isInteger(ag)||hg<0||ag<0) return [];
    const event=String(match.frontEndId||"").trim();
    if(!event) return [];
    return [{
      hkjc_event_id:event,
      match_id:text(match.id),
      kickoff_hkt:ts(match.kickOffTime),
      tournament:text(match.tournament?.code),
      home:text(match.homeTeam?.name_en || match.homeTeam?.name_ch),
      away:text(match.awayTeam?.name_en || match.awayTeam?.name_ch),
      home_goals:hg,
      away_goals:ag,
      outcome:hg>ag?"H":ag>hg?"A":"D",
      payout_confirmed:ft.payoutConfirmed === true || String(ft.payoutConfirmed).toLowerCase()==="true",
      fetched_at:fetched,
      raw:match
    }];
  });

  const {data:upserted,error}=await db.rpc("ft_internal_upsert_results",{payload:rows});
  if(error) throw new Error("results upsert: "+error.message);
  const {data:validation,error:ve}=await db.rpc("ft_internal_refresh_validation");
  if(ve) throw new Error("validation refresh: "+ve.message);
  return {startDate,endDate,total_returned:matches.length,settled_rows:rows.length,upserted,validation};
}

async function capturePrematch() {
  const {data,error}=await db.rpc("ft_internal_capture_prematch");
  if(error) throw new Error("prematch capture: "+error.message);
  return data;
}

async function refreshDecisions() {
  const {data,error}=await db.rpc("ft_internal_refresh_phase1_decisions");
  if(error) throw new Error("decision refresh: "+error.message);
  return data;
}

async function syncArchive() {
  const rows = await csvAsset("forebet_archive.csv");
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

  const ev = await csvAsset("evaluation_summary.csv");
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
    let result: Record<string,unknown>;
    if (mode === "live") {
      result = await syncLive();
    } else if (mode === "results") {
      result = await syncResultsDirect();
    } else if (mode === "archive") {
      const directResults = await syncResultsDirect();
      let legacyArchive: Record<string,unknown>;
      try {
        legacyArchive = await syncArchive();
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        legacyArchive = { ok:false, preserved_last_known_good:true, error:message };
        await db.from("source_health").upsert({
          source:"GITHUB_ARCHIVE_SYNC", metric:"archive", value_text:message,
          status:"WARN", notes:"Private GitHub archive unavailable; direct HKJC results still refreshed",
          observed_at:new Date().toISOString(), raw:{error:message}
        },{onConflict:"source,metric"});
      }
      result = { direct_results: directResults, legacy_archive: legacyArchive };
    } else {
      result = await syncCurrent();
      try {
        result.multisource = await syncMultiSource();
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        result.multisource = { ok:false, preserved_last_known_good:true, error:message };
        await db.from("source_health").upsert({
          source:"MULTISOURCE_SYNC", metric:"current", value_text:message,
          status:"WARN", notes:"Preserved last-known-good Multi-source Intelligence Layer",
          observed_at:new Date().toISOString(), raw:{error:message}
        },{onConflict:"source,metric"});
      }
      result.canonical_core = await refreshCanonicalCore();
      result.prematch_snapshot = await capturePrematch();
      result.phase1_decisions = await refreshDecisions();
    }

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
