import Link from "next/link";
import { notFound } from "next/navigation";
import ProbabilityRow from "@/components/probability-row";
import {
  fairMarket,
  formatKickoff,
  formatOdds,
  getMatch,
  divergence,
  modelLabel,
  sideName,
} from "@/lib/fast-tracker";

export default async function MatchDetail({ params }) {
  const { id } = await params;
  const match = getMatch(id);
  if (!match) notFound();

  const market = fairMarket(match.odds);
  const gap = divergence(match);

  return (
    <main className="shell detail-shell">
      <div className="detail-top">
        <Link href="/" className="back">← 返回</Link>
        <span>{match.id}</span>
      </div>

      <section className="detail-hero">
        <div className="detail-meta">{formatKickoff(match.kickoff)} · {match.league}</div>
        <h1>{match.home}</h1>
        <p>vs</p>
        <h1>{match.away}</h1>
        <span className="status-pill large">校準中 · 暫不輸出正式投注指令</span>
      </section>

      <section className="panel">
        <div className="panel-title">
          <div><p>HKJC 1X2</p><h2>市場價格</h2></div>
        </div>
        <div className="big-odds">
          <div><span>主</span><b>{formatOdds(match.odds.home)}</b></div>
          <div><span>和</span><b>{formatOdds(match.odds.draw)}</b></div>
          <div><span>客</span><b>{formatOdds(match.odds.away)}</b></div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          <div><p>PROBABILITY</p><h2>市場 vs 模型</h2></div>
          <span>{modelLabel(match)}</span>
        </div>
        <ProbabilityRow label="HKJC no-vig" values={market} />
        {match.forebet && <ProbabilityRow label="Forebet" values={match.forebet} />}
        {match.multi && <ProbabilityRow label={`Multi-source · ${match.multi.sources}`} values={match.multi} strong />}
      </section>

      <section className="panel">
        <div className="panel-title"><div><p>DIVERGENCE</p><h2>值得留意嘅差異</h2></div></div>
        {gap ? (
          <div className="gap-feature">
            <span>{gap.key}</span>
            <div>
              <small>{sideName(match, gap.key)}</small>
              <b>{gap.value > 0 ? "+" : ""}{(gap.value * 100).toFixed(1)}pp</b>
            </div>
          </div>
        ) : (
          <p className="empty">未有足夠外部模型資料。</p>
        )}
        <p className="fineprint">呢個畫面只展示市場同模型之間嘅資料差異。正式 decision engine 仍然 validation-gated。</p>
      </section>
    </main>
  );
}
