import MatchCard from "@/components/match-card";
import { allMatches, divergence } from "@/lib/fast-tracker";

const filters = [
  ["all", "全部"],
  ["models", "有模型"],
  ["gaps", "分歧"],
  ["missing", "缺資料"],
];

export default async function Home({ searchParams }) {
  const params = await searchParams;
  const filter = params?.filter || "all";
  let matches = allMatches();

  if (filter === "models") matches = matches.filter((m) => m.multi || m.forebet);
  if (filter === "missing") matches = matches.filter((m) => !m.multi && !m.forebet);
  if (filter === "gaps") {
    matches = matches
      .filter((m) => divergence(m))
      .sort((a, b) => Math.abs(divergence(b).value) - Math.abs(divergence(a).value));
  }

  const total = allMatches().length;
  const modeled = allMatches().filter((m) => m.multi || m.forebet).length;
  const rich = allMatches().filter((m) => (m.multi?.sources || 0) >= 5).length;
  const maxGap = allMatches()
    .map(divergence)
    .filter(Boolean)
    .reduce((best, x) => !best || Math.abs(x.value) > Math.abs(best.value) ? x : best, null);

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">FAST TRACKER 2026</p>
          <h1>今日賽事情報</h1>
          <p className="subtitle">HKJC 做主軸 · 模型只作 evidence · decision 尚在校準</p>
        </div>
        <span className="preview-badge">APP V1 PREVIEW</span>
      </header>

      <section className="stats">
        <div><span>賽事</span><b>{total}</b></div>
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
          <h2>{filter === "gaps" ? "模型與市場分歧" : "Upcoming"}</h2>
          <p>{matches.length} 場 · 香港時間</p>
        </div>
        <span>只顯示 snapshot preview</span>
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
