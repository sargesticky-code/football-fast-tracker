import Link from "next/link";
import {
  coverage,
  divergence,
  formatKickoff,
  formatOdds,
  modelLabel,
  sideName,
} from "@/lib/fast-tracker";

export default function MatchCard({ match }) {
  const gap = divergence(match);
  const gapAbs = gap ? Math.abs(gap.value) : null;

  return (
    <Link className="match-card" href={`/match/${match.id}`}>
      <div className="match-topline">
        <span>{formatKickoff(match.kickoff)}</span>
        <span className="league">{match.league}</span>
        <span className={`coverage coverage-${coverage(match).replaceAll(" ", "-").toLowerCase()}`}>
          {coverage(match)}
        </span>
      </div>

      <div className="teams">
        <div><b>{match.home}</b><small>主</small></div>
        <span>vs</span>
        <div><b>{match.away}</b><small>客</small></div>
      </div>

      <div className="odds-strip">
        <div><span>主</span><b>{formatOdds(match.odds.home)}</b></div>
        <div><span>和</span><b>{formatOdds(match.odds.draw)}</b></div>
        <div><span>客</span><b>{formatOdds(match.odds.away)}</b></div>
      </div>

      <div className="signal-line">
        <div>
          <span className="muted">{modelLabel(match)}</span>
          {gap ? (
            <strong className={gapAbs >= 0.08 ? "gap-hot" : ""}>
              最大分歧 {sideName(match, gap.key)} {gap.value > 0 ? "+" : ""}{(gap.value * 100).toFixed(1)}pp
            </strong>
          ) : (
            <strong>暫無外部模型</strong>
          )}
        </div>
        <span className="status-pill">{match.decision === "CALIBRATION_PENDING" ? "校準中" : match.decision}</span>
      </div>
    </Link>
  );
}
