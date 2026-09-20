import MatchCard from "@/components/match-card";
import { getFeed, divergence } from "@/lib/fast-tracker";

const filters = [
  ["all", "全部"],
  ["models", "有模型"],
  ["gaps", "分歧"],
  ["missing", "缺資料"],
];

export default async function Home({ searchParams }) {
  const params = await searchParams;
  const filter = params?.filter || "all";
  const feed = await getFeed();
  const all = feed.matches;
  let matches = all;

  if (filter === "models") matches = matches.filter((m) => m.multi || m.forebet || m.dc || m.pi || m.form);
  if (filter === "missing") matches = matches.filter((m) => !m.multi && !m.forebet && !m.dc && !m.pi && !m.form);
  if (filter === "gaps") {
    matches = matches.filter((m) => divergence(m))
      .sort((a, b) => Math.abs(divergence(b).value) - Math.abs(divergence(a).value));
  }

  const modeled = all.filter((m) => m.multi || m.forebet || m.dc || m.pi || m.form).length;
  const rich = all.filter((m) => (m.multi?.sources || 0) >= 5).length;
  const maxGap = all.map(divergence).filter(Boolean)
    .reduce((best, x) => !best || Math.abs(x.value) > Math.abs(best.value) ? x : best, null);
  const isLive = feed.source === "supabase-canonical-live";

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">FAST TRACKER 2026</p>
          <h1>今日賽事情報</h1>
          <p className="subtitle">HKJC 做主軸 · 模型只作 evidence · decision 尚在校準</p>
        </div>
        <span className={`preview-badge ${isLive ? "live-badge" : ""}`}>
          {isLive ? "LIVE SQL" : "FALLBACK"}
        </span>
      </header>

      <section className="stats">
        <div><span>24H 賽事</span><b>{all.length}</b></div>
        <div><span>有模型</span><b>{modeled}</b></div>
        <div><span>5+ Sources</span><b>{rich}</b></div>
        <div><span>最大分歧</span><b>{maxGap ? `${Math.abs(maxGap.value * 100).toFixed(1)}pp` : "—"}</b></div>
      </section>

      <nav className="filters">
        {filters.map(([key, label]) => (
          <a key={key} className={filter === key ? "active" : ""} href={key === "all" ? "/" : `/?filter=${key}`}>
            {label}
          </a>
        ))}
      </nav>

      <section className="section-head">
        <div>
          <h2>{filter === "gaps" ? "模型與市場分歧" : "Upcoming 24H"}</h2>
          <p>{matches.length} 場 · 香港時間</p>
        </div>
        <span>{isLive ? "Canonical live feed" : "Snapshot fallback"}</span>
      </section>

      <div className="match-list">
        {matches.map((match) => <MatchCard key={match.id} match={match} />)}
      </div>

      <footer className="bottom-nav">
        <a className="selected" href="/">賽事</a>
        <span>Live</span>
        <span>模型</span>
        <span>系統</span>
      </footer>
    </main>
  );
}
