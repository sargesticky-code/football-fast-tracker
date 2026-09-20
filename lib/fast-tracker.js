import snapshot from "@/data/app_snapshot.json";

export function allMatches() {
  return snapshot.matches;
}

export function getMatch(id) {
  return snapshot.matches.find((m) => m.id === id) || null;
}

export function fairMarket(odds) {
  const inv = {
    home: 1 / odds.home,
    draw: 1 / odds.draw,
    away: 1 / odds.away,
  };
  const total = inv.home + inv.draw + inv.away;
  return {
    home: inv.home / total,
    draw: inv.draw / total,
    away: inv.away / total,
  };
}

export function preferredModel(match) {
  return match.multi || match.forebet || null;
}

export function modelLabel(match) {
  if (match.multi) return `Multi-source · ${match.multi.sources} sources`;
  if (match.forebet) return "Forebet";
  return "No external model";
}

export function divergence(match) {
  const model = preferredModel(match);
  if (!model) return null;
  const market = fairMarket(match.odds);
  const diffs = [
    { key: "H", value: model.home - market.home },
    { key: "D", value: model.draw - market.draw },
    { key: "A", value: model.away - market.away },
  ];
  return diffs.sort((a, b) => Math.abs(b.value) - Math.abs(a.value))[0];
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

export function sideName(match, key) {
  if (key === "H") return match.home;
  if (key === "A") return match.away;
  return "和";
}

export function coverage(match) {
  if (match.multi?.sources >= 5) return "DATA RICH";
  if (match.multi || match.forebet) return "MODEL DATA";
  return "HKJC ONLY";
}
