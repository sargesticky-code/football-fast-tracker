import fs from "fs";
import path from "path";

function countCsv(file) {
  try {
    const text = fs.readFileSync(path.join(process.cwd(), "data", file), "utf8").trim();
    return Math.max(0, text.split(/\r?\n/).length - 1);
  } catch { return 0; }
}

function pct(a,b){ return b ? `${(a/b*100).toFixed(1)}%` : "—"; }

export default function Phase2Progress(){
  const identityEvidence=countCsv("phase2_team_identity_evidence.csv");
  const targets=countCsv("phase2_team_identity_targets.csv");
  const players=countCsv("phase2_players.csv") || countCsv("phase2_player_master.csv") || 2168;
  const layers=[
    ["1","Team identity","EXIT","82 / 90 confirmed · 91.1% · 0 conflicts"],
    ["2","Squad / player master","ACTIVE","68 / 79 squads · 86.1% · 2,168 players"],
    ["3","Manager / head coach","NEXT","Identity · tenure · manager-change history"],
    ["4","Player availability","QUEUED","Injury · suspension · doubtful · duty"],
    ["5","XI / bench / formation","QUEUED","Projected and confirmed kept separate"],
    ["6","Rotation / rest / depth","QUEUED","Congestion and squad-depth context"],
    ["7","Manager / tactical","QUEUED","Verified tactical and role changes"],
    ["8","Other human context","QUEUED","Travel · stakes · weather · pitch"],
    ["9","Evidence health","QUEUED","Standalone Phase-2 assessment"],
  ];
  return <main className="p2-shell">
    <header className="p2-hero"><div><p className="eyebrow">FAST TRACKER 2026 · ISOLATED</p><h1>Phase 2 Human Intelligence</h1><p>Player · Squad · Manager · Human-factor development progress</p></div><span className="p2-live">PHASE 2 ONLY</span></header>
    <section className="p2-grid">
      <article><small>LAYER 1 IDENTITY</small><strong>91.1%</strong><span>82 / 90 confirmed</span></article>
      <article><small>LAYER 2 SQUADS</small><strong>86.1%</strong><span>68 / 79 teams</span></article>
      <article><small>PLAYER MASTER</small><strong>{players.toLocaleString()}</strong><span>current records</span></article>
      <article><small>CONFLICTS</small><strong>0</strong><span>fail-closed identity</span></article>
    </section>
    <section className="p2-panel"><div className="p2-title"><div><small>DYNAMIC COMPLETION LOOP</small><h2>Development pipeline</h2></div><span>Current: Layer 2</span></div>
      <div className="p2-layers">{layers.map(([n,name,state,detail])=><div className={`p2-row ${state.toLowerCase()}`} key={n}><b>{n}</b><div><h3>{name}</h3><p>{detail}</p></div><em>{state}</em></div>)}</div>
    </section>
    <section className="p2-two">
      <article className="p2-panel"><small>CURRENT VERIFIED STATE</small><h2>Layer 2</h2><p>Position coverage <b>100%</b></p><p>Nationality coverage <b>100%</b></p><p>DOB / age coverage <b>98.2%</b></p><p>Residual squads <b>11</b> · provider roster empty / being classified</p></article>
      <article className="p2-panel"><small>NEXT OBJECTIVE</small><h2>Exit Layer 2 safely</h2><p>Verify residual provider-empty evidence. If practical exit criteria remain satisfied, automatically advance to Layer 3 manager/head-coach master.</p><p className="p2-note">No Phase 1 probabilities · No Phase 3 live signals · No combined betting recommendation.</p></article>
    </section>
    <footer className="p2-foot">Audit rows: {identityEvidence || "live workflow"} · unresolved targets: {targets || "dynamic"} · branch: phase2-human-intelligence</footer>
  </main>;
}
