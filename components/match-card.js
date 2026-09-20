import Link from "next/link";
import {
  coverage,
  divergence,
  formatKickoff,
  formatOdds,
  freshness,
  modelCoverageCount,
  reviewScore,
  sideName,
} from "@/lib/fast-tracker";

export default function MatchCard({ match, nowMs, focusRank = null }) {
  const gap = divergence(match);
  const gapAbs = gap ? Math.abs(gap.value) : null;
  const fresh = freshness(match, nowMs);
  const sourceCount = modelCoverageCount(match);
  const score = reviewScore(match, nowMs);
  const primaryHome = match.homeZh || match.home;
  const primaryAway = match.awayZh || match.away;
  const secondaryHome = match.homeZh ? match.home : null;
  const secondaryAway = match.awayZh ? match.away : null;

  return (
    <Link className={`match-card ${focusRank ? "focus-card" : ""}`} href={`/match/${match.id}`}>
      <div className="match-topline">
        {focusRank ? <span className="focus-rank">#{focusRank}</span> : null}
        <span>{formatKickoff(match.kickoff)}</span>
        <span className="league">{match.league}</span>
        <span className={`freshness freshness-${fresh.key}`}>{fresh.label}</span>
      </div>

      <div className="teams">
        <div>
          <b>{primaryHome}</b>
          {secondaryHome && <em>{secondaryHome}</em>}
          <small>主</small>
        </div>
        <span>vs</span>
        <div>
          <b>{primaryAway}</b>
          {secondaryAway && <em>{secondaryAway}</em>}
          <small>客</small>
        </div>
      </div>

      <div className="odds-strip">
        <div><span>主</span><b>{formatOdds(match.odds.home)}</b></div>
        <div><span>和</span><b>{formatOdds(match.odds.draw)}</b></div>
        <div><span>客</span><b>{formatOdds(match.odds.away)}</b></div>
      </div>

      <div className="signal-line">
        <div>
          <span className="muted">{sourceCount ? `${sourceCount} 個 evidence inputs` : "HKJC only"}</span>
          {gap ? (
            <strong className={gapAbs >= 0.08 ? "gap-hot" : ""}>
              市場分歧 {sideName(match, gap.key)} {gap.value > 0 ? "+" : ""}{(gap.value * 100).toFixed(1)}pp
            </strong>
          ) : (
            <strong>未有外部模型比較</strong>
          )}
        </div>
        <div className="card-badges">
          <span className={`coverage coverage-${coverage(match).replaceAll(" ", "-").toLowerCase()}`}>{coverage(match)}</span>
          {focusRank ? <span className="review-score">Review {score}</span> : null}
        </div>
      </div>
    </Link>
  );
}
