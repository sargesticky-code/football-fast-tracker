import { countCsv, parseCsv, phase2Summary } from "@/lib/phase2-data";

function SourceLink({href,label}){ return href ? <a href={href} target="_blank" rel="noreferrer">{label}</a> : <span>{label}</span>; }

export default function Phase2Progress(){
 const p=phase2Summary(), i=p.identity, s=p.squad, m=p.manager, r=p.rotation, reep=p.reep;
 const ps=parseCsv("phase2_player_master.csv",8), ms=parseCsv("phase2_manager_master.csv",8), xs=parseCsv("phase2_reep_crosswalk.csv",8);
 const layers=[
  [1,"Team identity",i.layer1_exit?"EXIT":"ACTIVE",`${i.confirmed||0} / ${i.unique_teams||0} confirmed · ${i.coverage_pct||0}% · ${i.conflicts||0} conflicts`],
  [2,"Squad / player master",s.layer2_exit?"EXIT":"ACTIVE",`${s.teams_with_squad||0} / ${s.target_confirmed_fotmob_teams||0} squads · ${s.team_coverage_pct||0}% · ${p.players.toLocaleString()} player rows`],
  [3,"Manager / head coach",m.layer3_exit?"EXIT":"ACTIVE",`${m.teams_with_explicit_manager||0} / ${m.target_confirmed_fotmob_teams||0} explicit managers · ${m.team_coverage_pct||0}%`],
  [4,"Current availability","BUILDING","Injury · suspension · doubtful · return · international duty"],
  [5,"XI / bench / formation","BUILDING","Projected and official strictly separated"],
  [6,"Rotation / rest / depth",r.layer6_exit?"EXIT":"ACTIVE",`${r.depth_fact_sides||0} depth-covered sides · ${r.rotation_verified_sides||0} verified rotation sides`],
  [7,"Manager / tactical","QUEUED","Verified tactical and role changes"],
  [8,"Other human context","QUEUED","Travel · stakes · weather · pitch"],
  [9,"Evidence health","QUEUED","Standalone Phase-2 assessment"]
 ];
 return <main className="p2-shell">
  <header className="p2-hero"><div><p className="eyebrow">FAST TRACKER 2026 · SOURCEABLE HUMAN INTELLIGENCE</p><h1>Phase 2 Human Intelligence</h1><p>Every visible player/manager row comes from generated evidence. Identity crosswalks are corroboration only.</p></div><span className="p2-live">PHASE 2 ONLY</span></header>
  <section className="p2-grid">
   <article><small>IDENTITY</small><strong>{i.coverage_pct??"—"}%</strong><span>{i.confirmed||0}/{i.unique_teams||0} teams · {i.conflicts||0} conflicts</span></article>
   <article><small>SQUADS</small><strong>{s.team_coverage_pct??"—"}%</strong><span>{s.teams_with_squad||0}/{s.target_confirmed_fotmob_teams||0} teams</span></article>
   <article><small>PLAYER MASTER</small><strong>{p.players.toLocaleString()}</strong><span>current FACT rows</span></article>
   <article><small>MANAGERS</small><strong>{p.managers.toLocaleString()}</strong><span>{m.team_coverage_pct??"—"}% team coverage</span></article>
  </section>
  <section className="p2-panel"><div className="p2-title"><div><small>DYNAMIC COMPLETION LOOP</small><h2>Actual pipeline state</h2></div><span>Current blocker: Layer {p.layer}</span></div><div className="p2-layers">{layers.map(([n,name,state,detail])=><div className={`p2-row ${String(state).toLowerCase()}`} key={n}><b>{n}</b><div><h3>{name}</h3><p>{detail}</p></div><em>{state}</em></div>)}</div></section>
  <section className="p2-two">
   <article className="p2-panel"><small>REAL OUTPUT · PLAYER MASTER</small><h2>{p.players.toLocaleString()} rows</h2>{ps.map((x,k)=><p key={k}><b>{x.hkjc_team_name}</b> · {x.canonical_name} · {x.position} · <SourceLink href={x.source_url} label={x.provider||"source"} /></p>)}</article>
   <article className="p2-panel"><small>REAL OUTPUT · MANAGER MASTER</small><h2>{p.managers.toLocaleString()} rows</h2>{ms.map((x,k)=><p key={k}><b>{x.hkjc_team_name}</b> · {x.canonical_name} · <SourceLink href={x.source_url} label={x.provider||"source"} /></p>)}</article>
  </section>
  <section className="p2-two">
   <article className="p2-panel"><small>IDENTITY CORROBORATION · REEP</small><h2>{reep.resolved||0} cross-provider matches</h2><p>Use: <b>{reep.use||"identity corroboration only"}</b></p><p>Resolution: <b>{reep.resolution_pct??0}%</b></p><p>Freshness: <b>{reep.register||"not yet generated"}</b></p>{xs.slice(0,5).map((x,k)=><p key={k}>{x.canonical_name} · FM {x.fotmob_id} · TM {x.transfermarkt_id||"—"} · SS {x.sofascore_id||"—"}</p>)}<p><SourceLink href="https://github.com/withqwerty/reep" label="Reep GitHub source" /></p></article>
   <article className="p2-panel"><small>AUDIT HEALTH</small><h2>Fail closed</h2><p>Identity residual evidenced: <b>{i.residual_evidenced||0}</b></p><p>Squad residual: <b>{Object.keys(s.failure_classes||{}).join(", ")||"none"}</b></p><p>Manager residual: <b>{Object.keys(m.failure_classes||{}).join(", ")||"none"}</b></p><p>Reep never upgrades current injuries/lineups; it only corroborates identity.</p></article>
  </section>
  <section className="p2-panel"><small>CURRENT BLOCKER</small><h2>Layer 6 rotation/history</h2><p>Depth facts: <b>{r.depth_fact_sides||0}/{r.team_sides||0}</b> sides · verified rotation history: <b>{r.rotation_verified_sides||0}/{r.team_sides||0}</b>.</p><p>{r.next_objective||"Continue dynamic completion loop"}</p></section>
  <footer className="p2-foot">{i.matches||0}-fixture current universe · branch: phase2-human-intelligence · sourceable evidence, not betting output</footer>
 </main>;
}
