import "jsr:@supabase/functions-js/edge-runtime.d.ts";

// Read-only, bounded, sanctioned public source evidence; no provider login,
// no model identity promotion and no leaked Supabase service role credential.
const headers = {
  "access-control-allow-origin":"*",
  "access-control-allow-methods":"GET,OPTIONS",
  "access-control-allow-headers":"content-type",
  "cache-control":"public,max-age=60"
};
Deno.serve(async(req:Request):Promise<Response>=>{
  if(req.method==="OPTIONS")return new Response(null,{status:204,headers});
  if(req.method!=="GET")return Response.json({error:"READ_ONLY"},{status:405,headers});
  const url=Deno.env.get("SUPABASE_URL");
  // Prefer Supabase's current secret API key; retain a legacy JWT fallback.
  // Modern sb_secret_* keys MUST be sent only in the apikey header.
  let modernKey: string | undefined;
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
    if (typeof keys?.default === "string") modernKey = keys.default;
  } catch { /* Fall back to legacy only if no usable modern key. */ }
  const secret=modernKey || Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if(!url||!secret)return Response.json({error:"SERVICE_UNAVAILABLE"},{status:503,headers});
  try {
    const response=await fetch(url+"/rest/v1/rpc/ft_public_extra_adviser_provisional",{
      method:"POST",
      headers:{
        apikey: secret,
        ...(secret.startsWith("sb_secret_") ? {} : { authorization: "Bearer " + secret }),
        "content-type":"application/json",accept:"application/json",
        "cache-control":"no-store"},
      body:"{}",signal:AbortSignal.timeout(12000)
    });
    if(!response.ok){
      console.error("EXTRA_PROVISIONAL_FEED_RPC_ERROR",response.status);
      return Response.json({error:"SOURCE_UNAVAILABLE"},{status:503,headers});
    }
    const data=await response.json();
    if(!["EXTRA_ADVISER_PROVISIONAL_04","EXTRA_ADVISER_PROVISIONAL_03"].includes(data?.source) ||
      data?.quality!=="PROVISIONAL_NOT_VERIFIED_CALIBRATED_WALL_TIME" ||
      !Array.isArray(data?.rows)||data.rows.length>600 ||
      !data.rows.every((x:any)=> x.status==="PROVISIONAL_NOT_VERIFIED" &&
        x.kickoffTimezoneVerified===false &&
        ["PRIMATIPS","STATAREA"].includes(x.provider) &&
        typeof x.id==="string" && /^FS:[A-Za-z0-9_-]{5,32}$/.test(x.id))){
      return Response.json({error:"INVALID_SOURCE_CONTRACT"},{status:503,headers});
    }
    return Response.json(data,{status:200,headers});
  }catch{
    return Response.json({error:"SOURCE_TIMEOUT"},{status:503,headers});
  }
});