import fs from "fs";
import path from "path";

const D=path.join(process.cwd(),"data");

export function readJson(file){
  try{return JSON.parse(fs.readFileSync(path.join(D,file),"utf8"))}catch{return {}}
}
export function countCsv(file){
  try{
    const t=fs.readFileSync(path.join(D,file),"utf8").replace(/^\uFEFF/,"").trim();
    return t?Math.max(0,t.split(/\r?\n/).length-1):0;
  }catch{return 0}
}
export function parseCsv(file,limit=Infinity){
  try{
    const text=fs.readFileSync(path.join(D,file),"utf8").replace(/^\uFEFF/,"");
    const rows=[]; let row=[],cell="",q=false;
    for(let i=0;i<text.length;i++){
      const ch=text[i],nx=text[i+1];
      if(ch=='"'&&q&&nx=='"'){cell+='"';i++;continue}
      if(ch=='"'){q=!q;continue}
      if(ch==','&&!q){row.push(cell);cell="";continue}
      if((ch=='\n'||ch=='\r')&&!q){
        if(ch=='\r'&&nx=='\n')i++;
        row.push(cell);cell="";
        if(row.some(x=>x!==""))rows.push(row);
        row=[];
        continue;
      }
      cell+=ch;
    }
    if(cell||row.length){row.push(cell);rows.push(row)}
    const h=rows.shift()||[];
    return rows.slice(0,limit).map(r=>Object.fromEntries(h.map((k,i)=>[k,r[i]??""])));
  }catch{return []}
}
export function phase2Summary(){
  const identity=readJson("phase2_identity_health.json");
  const squad=readJson("phase2_squad_health.json");
  const manager=readJson("phase2_manager_health.json");
  const rotation=readJson("phase2_rotation_health.json");
  const reep=readJson("phase2_reep_health.json");
  const layer= !identity.layer1_exit?1:!squad.layer2_exit?2:!manager.layer3_exit?3:!rotation.layer6_exit?6:7;
  return {identity,squad,manager,rotation,reep,layer,players:countCsv("phase2_player_master.csv"),managers:countCsv("phase2_manager_master.csv")};
}
