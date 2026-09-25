import fs from "fs";
import path from "path";

const D=path.join(process.cwd(),"data");
function json(file){try{return JSON.parse(fs.readFileSync(path.join(D,file),"utf8"))}catch{return {}}}
function countCsv(file){try{return Math.max(0,fs.readFileSync(path.join(D,file),"utf8").trim().split(/\r?\n/).length-1)}catch{return 0}}
function sampleCsv(file,n=8){try{const lines=fs.readFileSync(path.join(D,file),"utf8").replace(/^\uFEFF/,"").trim().split(/\r?\n/);const h=lines[0].split(',');return lines.slice(1,n+1).map(x=>{const c=x.split(',');return Object.fromEntries(h.map((k,i)=>[k,c[i]||""]))})}catch{return []}}

export default function Phase2Progress(){
 const i=json("phase2_identity_health.json"),s=json("phase2_squad_health.json"),m=json("phase2_manager_health.json"),r=json("phase2_rotation_health.json");
 const players=countCsv("phase2_player_master.csv"),managers=countCsv("phase2_manager_master.csv");
 const ps=sampleCsv("phase2_player_master.csv",6),ms=sampleCsv("phase2_manager_master.csv",6);
 const current=!i.layer1_exit?1:!s.layer2_exit?2:!m.residual_all_classified?3:6;
 const layers=[
  [1,"Team identity",i.layer1_exit?"EXIT":"ACTIVE",`${i.confirmed||0} / ${i.unique_teams||0} confirmed · ${i.coverage_pct||0}% · ${i.conflicts||0} conflicts`],
  [2,"Squad / player master",s.layer2_exit?"EXIT":"ACTIVE",`${s.teams_with_squad||0} / ${s.target_confirmed_fotmob_teams||0} squads · ${s.team_coverage_pct||0}% · ${players.toLocaleString()} player rows`],
  [3,"Manager / head coach",m.residual_all_classified?"EXIT":"ACTIVE",`${m.teams_with_explicit_manager||0} / ${m.target_confirmed_fotmob_teams||0} explicit managers · ${m.team_coverage_pct||0}%`],
  [4,"Current availability","BUILDING","Injury · suspension · doubtful · return · international duty"],
  [5,"XI / bench / formation","BUILDING","Projected and official strictly separated"],
  [6,"Rotation / rest / depth",r.layer6_exit?"EXIT":"ACTIVE",`${r.depth_fact_sides||0} depth-covered sides · ${r.rotation_verified_sides||0} verified rotation sides`],
  [7,"Manager / tactical","QUEUED","Verified tactical and role changes"],[8,"Other human context","QUEUED","Travel · stakes · weather · pitch"],[9,"Evidence health","QUEUED","Standalone Phase-2 assessment"]
 ];
 return <main className="p2-shell">
  <header className="p2-hero"><div><p className="eyebrow">FAST TRACKER 2026 · LIVE BRANCH DATA</p><h1>Phase 2 Human Intelligence</h1><p>This page now reads generated Phase-2 evidence files instead of hard-coded progress.</p></div><span className="p2-live">PHASE 2 ONLY</span></header>
  <section className="p2-grid">
   <article><small>IDENTITY</small><strong>{i.coverage_pct??"—"}%</strong><span>{i.confirmed||0}/{i.unique_teams||0} teams · {i.conflicts||0} conflicts</span></article>
   <article><small>SQUADS</small><strong>{s.team_coverage_pct??"—"}%</strong><span>{s.teams_with_squad||0}/{s.target_confirmed_fotmob_teams||0} teams</span></article>
   <article><small>PLAYER MASTER</small><strong>{players.toLocaleString()}</strong><span>verified generated rows</span></article>
   <article><small>MANAGERS</small><strong>{managers.toLocaleString()}</strong><span>{m.team_coverage_pct??"—"}% team coverage</span></article>
  </section>
  <section className="p2-panel"><div className="p2-title"><div><small>DYNAMIC COMPLETION LOOP</small><h2>Actual pipeline state</h2></div><span>Current blocker: Layer {current}</span></div><div className="p2-layers">{layers.map(([n,name,state,detail])=><div className={`p2-row ${String(state).toLowerCase()}`} key={n}><b>{n}</b><div><h3>{name}</h3><p>{detail}</p></div><em>{state}</em></div>)}</div></section>
  <section className="p2-two">
   <article className="p2-panel"><small>REAL OUTPUT · PLAYER MASTER</small><h2>{players.toLocaleString()} rows</h2>{ps.map((x,k)=><p key={k}><b>{x.hkjc_team_name}</b> · {x.canonical_name} · {x.position}</p>)}</article>
   <article className="p2-panel"><small>REAL OUTPUT · MANAGER MASTER</small><h2>{managers.toLocaleString()} rows</h2>{ms.map((x,k)=><p key={k}><b>{x.hkjc_team_name}</b> · {x.canonical_name}</p>)}</article>
  </section>
  <section className="p2-two"><article className="p2-panel"><small>CURRENT BLOCKER</small><h2>Layer 6 rotation/history</h2><p>Depth facts: <b>{r.depth_fact_sides||0}/{r.team_sides||0}</b> sides.</p><p>Verified rotation history: <b>{r.rotation_verified_sides||0}/{r.team_sides||0}</b>.</p><p>{r.next_objective||"Continue dynamic completion loop"}</p></article><article className="p2-panel"><small>AUDIT HEALTH</small><h2>Fail closed</h2><p>Identity residual evidenced: <b>{i.residual_evidenced||0}</b></p><p>Squad residual class: <b>{Object.keys(s.failure_classes||{}).join(', ')||'none'}</b></p><p>Manager residual class: <b>{Object.keys(m.failure_classes||{}).join(', ')||'none'}</b></p></article></section>
  <footer className="p2-foot">98-fixture current universe · branch: phase2-human-intelligence · generated evidence, not betting output</footer>
 </main>;
}
