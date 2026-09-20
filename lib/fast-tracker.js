import snapshot from "@/data/app_snapshot.json";

const FEED_URL =
  process.env.FAST_TRACKER_FEED_URL ||
  "https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/app-phase1-feed?hours=24";

export async function getFeed() {
  try {
    const res = await fetch(FEED_URL, { next: { revalidate: 60 } });
    if (!res.ok) throw new Error(`feed_http_${res.status}`);
    const live = await res.json();
    if (!Array.isArray(live.matches)) throw new Error("feed_shape_invalid");
    return live;
  } catch (_) {
    return {
      generatedAt: snapshot.generatedAt,
      source: "snapshot-fallback",
      windowHours: 24,
      count: snapshot.matches.length,
      matches: snapshot.matches,
    };
  }
}

export async function getMatch(id) {
  const feed = await getFeed();
  return feed.matches.find((m) => m.id === id) || null;
}

export function fairMarket(odds) {
  if (!odds?.home || !odds?.draw || !odds?.away) return null;
  const inv = { home: 1 / odds.home, draw: 1 / odds.draw, away: 1 / odds.away };
  const total = inv.home + inv.draw + inv.away;
  return { home: inv.home / total, draw: inv.draw / total, away: inv.away / total };
}

export function preferredModel(match) {
  return match.multi || match.forebet || match.dc || match.pi || match.form || null;
}

export function modelLabel(match) {
  if (match.multi) return `Multi-source · ${match.multi.sources} sources`;
  if (match.forebet) return "Forebet";
  if (match.dc) return "DC";
  if (match.pi) return "Pi";
  if (match.form) return "Form";
  return "No external model";
}

export function divergence(match) {
  const model = preferredModel(match);
  const market = match.market || fairMarket(match.odds);
  if (!model || !market) return null;
  const diffs = [
    { key: "H", value: model.home - market.home },
    { key: "D", value: model.draw - market.draw },
    { key: "A", value: model.away - market.away },
  ];
  return diffs.sort((a, b) => Math.abs(b.value) - Math.abs(a.value))[0];
}

export function modelCoverageCount(match) {
  let count = 0;
  if (match.forebet) count += 1;
  if (match.dc) count += 1;
  if (match.pi) count += 1;
  if (match.form) count += 1;
  if (match.multi) count += Math.max(1, Number(match.multi.sources || 0));
  return count;
}

export function dataAgeMinutes(match, nowMs = Date.now()) {
  if (!match.updatedAt) return Infinity;
  const t = new Date(match.updatedAt).getTime();
  if (!Number.isFinite(t)) return Infinity;
  return Math.max(0, Math.round((nowMs - t) / 60000));
}

export function freshness(match, nowMs = Date.now()) {
  const age = dataAgeMinutes(match, nowMs);
  if (!Number.isFinite(age)) return { key: "missing", label: "未知更新", age };
  if (age <= 90) return { key: "fresh", label: age < 2 ? "剛更新" : `${age}m前`, age };
  if (age <= 360) return { key: "aging", label: `${Math.round(age / 60)}h前`, age };
  return { key: "stale", label: age < 1440 ? `${Math.round(age / 60)}h前` : `${Math.round(age / 1440)}d前`, age };
}

export function reviewScore(match, nowMs = Date.now()) {
  const gap = divergence(match);
  const coverage = modelCoverageCount(match);
  const fresh = freshness(match, nowMs);

  // Review priority only: data richness + model/market disagreement + freshness.
  // It is deliberately not a betting score.
  const coveragePoints = Math.min(55, coverage * 8);
  const gapPoints = gap ? Math.min(35, Math.abs(gap.value) * 250) : 0;
  const freshPoints = fresh.key === "fresh" ? 10 : fresh.key === "aging" ? 5 : 0;
  return Math.round(coveragePoints + gapPoints + freshPoints);
}

export function formatPct(value) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function formatOdds(value) {
  return value == null ? "—" : Number(value).toFixed(2);
}

export function formatKickoff(value) {
  return new Intl.DateTimeFormat("zh-HK", {
    timeZone: "Asia/Hong_Kong",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function formatUpdated(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-HK", {
    timeZone: "Asia/Hong_Kong",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function sideName(match, key) {
  if (key === "H") return match.homeZh || match.home;
  if (key === "A") return match.awayZh || match.away;
  return "和";
}

export function coverage(match) {
  const count = modelCoverageCount(match);
  if (count >= 6) return "DATA RICH";
  if (count > 0) return "MODEL DATA";
  return "HKJC ONLY";
}
