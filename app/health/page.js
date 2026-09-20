import Link from "next/link";
import { getFeed, modelCoverageCount, freshness } from "@/lib/fast-tracker";

export default async function HealthPage(){
  const feed=await getFeed(); const now=Date.now(); const matches=feed.matches||[];
  const stats={
    total:matches.length,
    modeled:matches.filter(m=>modelCoverageCount(m)>0).length,
    forebet:matches.filter(m=>m.forebet).length,
    multisource:matches.filter(m=>m.multi).length,
    stale:matches.filter(m=>freshness(m,now).key==="stale").length,
    missing:matches.filter(m=>m.health?.primaryMissingReason).length,
  };
  return <main className="shell detail-shell">
    <div className="detail-top"><Link href="/" className="back">← 賽事</Link><span>Phase 1 · canonical health</span></div>
    <section className="detail-hero"><p className="eyebrow">FAST TRACKER 2026</p><h1>Data Health</h1><p>只顯示 canonical database 狀態；source 出錯唔會假扮有資料。</p></section>
    <section className="health-strip"><div><b>{stats.total}</b><span>24H HKJC</span></div><div><b>{stats.modeled}</b><span>有模型</span></div><div><b>{stats.forebet}</b><span>Forebet</span></div><div><b>{stats.multisource}</b><span>Multi-source</span></div></section>
    <section className="panel"><div className="panel-title"><div><p>QUALITY</p><h2>Coverage</h2></div><span>{feed.source}</span></div>
      <div className="health-list"><div><span>過時資料</span><b>{stats.stale}</b></div><div><span>有 missing reason</span><b>{stats.missing}</b></div><div><span>Feed window</span><b>{feed.windowHours}h</b></div><div><span>Generated</span><b>{new Date(feed.generatedAt).toLocaleTimeString("zh-HK",{timeZone:"Asia/Hong_Kong",hour:"2-digit",minute:"2-digit"})}</b></div></div>
    </section>
    <section className="panel"><div className="panel-title"><div><p>POLICY</p><h2>Phase 1 safeguards</h2></div></div><p className="fineprint">HKJC係 betting universe。缺 source 就顯示 NO DATA；stale 唔當 current；Decision engine 保持 validation-gated，未有足夠校準唔輸出正式投注指令。</p></section>
  </main>;
}
