import MatchCard from "@/components/match-card";
import { phase2Summary } from "@/lib/phase2-data";
import {
  dataAgeMinutes,
  divergence,
  freshness,
  getFeed,
  modelCoverageCount,
  reviewScore,
} from "@/lib/fast-tracker";

const filters = [
  ["focus", "先睇"],
  ["all", "全部"],
  ["gaps", "分歧"],
  ["missing", "缺資料"],
  ["stale", "過時"],
];

export default async function Home() {
  const filter = "focus";
  const feed = await getFeed();
  const p2 = phase2Summary();
  const all = feed.matches;
  const nowMs = Date.now();

  const byFocus = [...all].sort((a, b) => {
    const scoreDelta = reviewScore(b, nowMs) - reviewScore(a, nowMs);
    if (scoreDelta) return scoreDelta;
    return new Date(a.kickoff) - new Date(b.kickoff);
  });

  let matches = byFocus;
  if (filter === "all") matches = [...all].sort((a, b) => new Date(a.kickoff) - new Date(b.kickoff));
  if (filter === "gaps") {
    matches = all.filter((m) => divergence(m))
      .sort((a, b) => Math.abs(divergence(b).value) - Math.abs(divergence(a).value));
  }
  if (filter === "missing") {
    matches = all.filter((m) => modelCoverageCount(m) === 0)
      .sort((a, b) => new Date(a.kickoff) - new Date(b.kickoff));
  }
  if (filter === "stale") {
    matches = all.filter((m) => freshness(m, nowMs).key === "stale")
      .sort((a, b) => dataAgeMinutes(b, nowMs) - dataAgeMinutes(a, nowMs));
  }

  const modeled = all.filter((m) => modelCoverageCount(m) > 0).length;
  const rich = all.filter((m) => modelCoverageCount(m) >= 6).length;
  const stale = all.filter((m) => freshness(m, nowMs).key === "stale").length;
  const missing = all.filter((m) => modelCoverageCount(m) === 0).length;
  const isLive = feed.source === "supabase-canonical-live";
  const focusFive = byFocus.filter((m) => modelCoverageCount(m) > 0).slice(0, 5);

  const headings = {
    focus: ["先睇呢批", "按資料完整度、模型分歧及新鮮度排序"],
    all: ["Upcoming 24H", "按開賽時間排序"],
    gaps: ["模型與市場分歧", "只比較已有外部模型嘅賽事"],
    missing: ["缺資料", "HKJC 有盤但暫時未有外部模型"],
    stale: ["過時資料", "超過 6 小時未更新"],
  };

  return (
    <main className="shell">
      <header className="hero compact-hero">
        <div>
          <p className="eyebrow">FAST TRACKER 2026</p>
          <h1>Match Intelligence</h1>
          <p className="subtitle">24小時 HKJC universe · 先睇資料，再睇 decision</p>
        </div>
        <span className={`preview-badge ${isLive ? "live-badge" : ""}`}>
          {isLive ? "LIVE SQL" : "FALLBACK"}
        </span>
      </header>

      <a href="/phase2" className="panel" style={{display:"block",marginBottom:12}}>
        <div className="section-head" style={{margin:0}}><div><h2>Phase 2 · Human Intelligence</h2><p>{p2.players.toLocaleString()} players · {p2.managers.toLocaleString()} managers · Layer {p2.layer} active</p></div><span>{p2.identity.coverage_pct??"—"}% identity</span></div>
      </a>

      <section className="health-strip">
        <div><b>{all.length}</b><span>24H賽事</span></div>
        <div><b>{modeled}</b><span>有模型</span></div>
        <div><b>{missing}</b><span>缺模型</span></div>
        <div className={stale ? "health-warn" : ""}><b>{stale}</b><span>過時</span></div>
      </section>

      {filter === "focus" && focusFive.length > 0 ? (
        <section className="focus-zone">
          <div className="focus-zone-head">
            <div><span>REVIEW FIRST</span><h2>最值得先檢視</h2></div>
            <p>呢個係資料優先級，唔係投注評分。</p>
          </div>
          <div className="focus-list">
            {focusFive.map((match, index) => (
              <MatchCard key={match.id} match={match} nowMs={nowMs} focusRank={index + 1} />
            ))}
          </div>
        </section>
      ) : null}

      <nav className="filters sticky-filters">
        {filters.map(([key, label]) => (
          <a key={key} className={filter === key ? "active" : ""} href={key === "focus" ? "/" : `/?filter=${key}`}>
            {label}
          </a>
        ))}
      </nav>

      <section className="section-head">
        <div>
          <h2>{headings[filter]?.[0] || headings.focus[0]}</h2>
          <p>{matches.length} 場 · 香港時間</p>
        </div>
        <span>{headings[filter]?.[1] || headings.focus[1]}</span>
      </section>

      <div className="match-list">
        {matches.map((match) => <MatchCard key={match.id} match={match} nowMs={nowMs} />)}
      </div>

      <footer className="bottom-nav">
        <a className="selected" href="/">賽事</a>
        <span>Live</span>
        <a href="/phase2">Human</a>
        <a href="/health">系統</a>
      </footer>
    </main>
  );
}
