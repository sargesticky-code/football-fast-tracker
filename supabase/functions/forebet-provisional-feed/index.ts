import "jsr:@supabase/functions-js/edge-runtime.d.ts";
// Read-only public visibility of *tentative* cross-provider associations.
// Source football names and forecasts are public; service token remains
// exclusively inside the Edge runtime. Never expose private audit or aliases.
const cors={"access-control-allow-origin":"*",
  "access-control-allow-methods":"GET,OPTIONS",
  "access-control-allow-headers":"content-type",
  "cache-control":"public, max-age=40"};
Deno.serve(async(req:Request):Promise<Response>=>{
  if(req.method==="OPTIONS")return new Response(null,{status:204,headers:cors});
  if(req.method!=="GET")return Response.json({error:"READ_ONLY"},{status:405,headers:cors});
  const base=Deno.env.get("SUPABASE_URL"),secret=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if(!base||!secret)return Response.json({error:"SOURCE_CONFIGURATION_MISSING"},{status:503,headers:cors});
  const query=new URLSearchParams({
    select:"canonical_event_id,kickoff_hkt,canonical_home,canonical_away,source_home,source_away,verified_side,source_url,source_model,last_seen_at,advisory_status",
    order:"kickoff_hkt.asc",limit:"180"
  });
  try{
    const r=await fetch(base+"/rest/v1/forebet_provisional_feed_current?"+query,{
      headers:{apikey:secret,authorization:"Bearer "+secret,accept:"application/json"},
      signal:AbortSignal.timeout(10_000)
    });
    if(!r.ok){console.error("FOREBET_PROVISIONAL_VIEW_READ_ERROR",r.status);
      return Response.json({error:"PROVISIONAL_FEED_UNAVAILABLE"},{status:503,headers:cors});}
    const data=await r.json();
    if(!Array.isArray(data)||data.length>180)
      return Response.json({error:"PROVISIONAL_FEED_INVALID"},{status:503,headers:cors});
    const rows=data.filter((x:any)=>
      /^FS:[A-Za-z0-9_-]{5,32}$/.test(String(x.canonical_event_id||""))
      && x.advisory_status==="PROVISIONAL_ONE_SIDE_NOT_VERIFIED"
      && ["HOME","AWAY"].includes(x.verified_side)
      && Number.isFinite(Date.parse(x.last_seen_at))
      && Date.parse(x.last_seen_at)>Date.now()-36*3600_000
      && Date.parse(x.kickoff_hkt)>Date.now()
    ).map((x:any)=>({
      id:x.canonical_event_id,kickoff:x.kickoff_hkt,
      home:x.canonical_home,away:x.canonical_away,
      sourceHome:x.source_home,sourceAway:x.source_away,
      matchedSide:x.verified_side,
      pick:x.source_model?.pick||null,
      probabilities:[x.source_model?.home,x.source_model?.draw,x.source_model?.away],
      predictedScore:x.source_model?.score||null,
      avgGoals:x.source_model?.avg_goals??null,
      sourceUrl:x.source_url,
      lastChecked:x.last_seen_at,status:"PROVISIONAL_NOT_VERIFIED"
    }));
    return Response.json({source:"FOREBET_PROVISIONAL",quality:"PROVISIONAL_NOT_VERIFIED",
      generatedAt:new Date().toISOString(),rows},{headers:cors});
  }catch{return Response.json({error:"PROVISIONAL_FEED_TIMEOUT"},{status:503,headers:cors});}
});