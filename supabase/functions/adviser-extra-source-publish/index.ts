import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";

// GitHub-signed source-only publisher. Does not promote any forecast to VERIFIED.
// Only this repository's exact main workflow may write to the private quarantine.
const jwks = createRemoteJWKSet(new URL("https://token.actions.githubusercontent.com/.well-known/jwks"));
const WF = "sargesticky-code/football-fast-tracker/.github/workflows/adviser-extra-source-evidence.yml@refs/heads/main";
const response=(status:number,value:Record<string,unknown>)=>
  Response.json(value,{status,headers:{"cache-control":"no-store"}});
Deno.serve(async(request:Request):Promise<Response>=>{
  if(request.method!=="POST")return response(405,{error:"METHOD_NOT_ALLOWED"});
  const auth=request.headers.get("authorization")||"";
  if(!auth.startsWith("Bearer "))return response(401,{error:"MISSING_OIDC"});
  let runId="";
  try {
    const verified=await jwtVerify(auth.slice(7),jwks,{
      issuer:"https://token.actions.githubusercontent.com",audience:"fast-tracker-supabase",
      algorithms:["RS256"],clockTolerance:"30s"
    });
    const c=verified.payload;
    if(c.repository!=="sargesticky-code/football-fast-tracker"
      ||c.ref!=="refs/heads/main"||c.workflow_ref!==WF
      ||!["push","schedule","workflow_dispatch"].includes(String(c.event_name))
      ||!/^[0-9]{6,20}$/.test(String(c.run_id))){
      return response(403,{error:"UNTRUSTED_SOURCE_CAPTURE_WORKFLOW"});
    }
    runId=String(c.run_id);
  }catch{return response(401,{error:"INVALID_GITHUB_OIDC"});}
  const url=Deno.env.get("SUPABASE_URL");
  const secret=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if(!url||!secret)return response(503,{error:"SERVICE_CONFIGURATION_UNAVAILABLE"});
  let body:any;
  try {
    const raw=await request.text();
    if(raw.length>1800000)return response(413,{error:"SOURCE_TOO_LARGE"});
    body=JSON.parse(raw);
  }catch{return response(400,{error:"INVALID_SOURCE_JSON"});}
  if(body?.contract!=="ADVISER_EXTRA_EVIDENCE_ONLY_V1"
    ||body?.publication_enabled!==false||!Array.isArray(body?.records)
    ||body.records.length<1||body.records.length>1500
    ||!Number.isFinite(Date.parse(String(body?.captured_at||"")))){
    return response(422,{error:"INVALID_SOURCE_EVIDENCE_ENVELOPE"});
  }
  try {
    const r=await fetch(url+"/rest/v1/rpc/ft_extra_adviser_publish_source_only",{
      method:"POST",headers:{apikey:secret,authorization:"Bearer "+secret,
        "content-type":"application/json",accept:"application/json","cache-control":"no-store"},
      body:JSON.stringify({
        p_rows:body.records,p_captured_at:body.captured_at,p_run_id:runId
      }),signal:AbortSignal.timeout(25000)
    });
    if(!r.ok){
      let code="UNKNOWN",detail="UNKNOWN";
      try {
        const fault=await r.json() as Record<string,unknown>;
        if(typeof fault.code==="string"&&/^[A-Z0-9]{5,12}$/.test(fault.code))code=fault.code;
        const safe=new Set(["INVALID_EXTRA_SOURCE_BATCH","INVALID_EXTRA_SOURCE_OBSERVATIONS",
          "DUPLICATE_EXTRA_SOURCE_IDS","EXTRA_SOURCE_WRITE_MISMATCH"]);
        if(typeof fault.message==="string"&&safe.has(fault.message))detail=fault.message;
      } catch { /* never echo source rows or service credentials */ }
      console.error("EXTRA_SOURCE_PRIVATE_QUARANTINE_FAILED",r.status,code,detail);
      return response(r.status>=500?503:422,{error:"PRIVATE_QUARANTINE_REJECTED"});
    }
    const data=await r.json();
    if(data?.source!=="EXTRA_ADVISER_SOURCE_ONLY"
      ||data?.stored!==body.records.length
      ||data?.verified_identity_count!==0
      ||data?.kickoff_timezone_verified_count!==0)
      return response(503,{error:"QUARANTINE_ACK_MISMATCH"});
    return response(200,{...data,production_forecasts_published:0});
  }catch{return response(503,{error:"SOURCE_QUARANTINE_TIMEOUT"});}
});