// YouTube publishing for the V3 team through the Leo Explains pipeline that already exists on this PC
// (stickman_series: release.json hand-over, release_order.json, upload_long.py / youtube_upload_short.py).
// The town does not build its own uploader: it calls those scripts with the AI Acency python, so the same
// preflight, AI disclosure, duplicate guard and studio vault are used, and it records every upload with
// release.py so the existing scheduled tasks see it. Shared rules from PUBLISHING_SCHEDULE.md enforced here:
// social/STOP stops everything, one account lock at a time, held episodes wait for their date,
// at most 2 long videos and 2 Shorts per day, at least 3 h apart, uploaded private with publishAt.
import {existsSync,readFileSync,readdirSync,writeFileSync,unlinkSync,statSync} from 'node:fs';
import {join} from 'node:path';
import {spawn} from 'node:child_process';

const DEFAULT_PROJECT='C:\\Users\\mario\\PyCharmMiscProject\\Market Signals V9\\stickman_series';
const DEFAULT_PYTHON='E:\\AI Acency\\Autonomous_AI_Studio_Documentation_v5_ECONOMY_TREASURY_VENDORSHOP\\.venv\\Scripts\\python.exe';
export const LEO_CHANNEL_ID='UCsJC65Up_k9TtKHA1eaEK3Q';
export const projectDir=()=>process.env.LEO_PROJECT_DIR||DEFAULT_PROJECT;
const python=()=>process.env.LEO_PYTHON||DEFAULT_PYTHON;
const channelId=()=>process.env.LEO_CHANNEL_ID||LEO_CHANNEL_ID;
const KIND={long:{step:'yt_long',script:'upload_long.py',result:'youtube_result.json',slots:[14,18],label:'video lung'},
 short:{step:'yt_short',script:'youtube_upload_short.py',result:'short_youtube_result.json',slots:[17,21],label:'Short'}};
const PER_DAY=2,GAP_H=3,LOCK_STALE_H=3;

let runner=(cmd,args,{cwd,timeout})=>new Promise(resolve=>{
 const env={...process.env,PYTHONIOENCODING:'utf-8',PATH:['C:\\Users\\mario\\bin',process.env.PATH||''].join(process.platform==='win32'?';':':')};
 const child=spawn(cmd,args,{cwd,env,windowsHide:true});let out='',err='';const timer=setTimeout(()=>child.kill(),timeout);
 child.stdout.on('data',b=>out+=b);child.stderr.on('data',b=>err+=b);
 child.on('error',e=>{clearTimeout(timer);resolve({code:-1,stdout:out,stderr:String(e.message)});});
 child.on('close',code=>{clearTimeout(timer);resolve({code,stdout:out,stderr:err});});
});
let clock=()=>new Date();
export function setPublishRunner(fn){runner=fn;}
export function setPublishClock(fn){clock=fn;}

const readJson=f=>{try{return JSON.parse(readFileSync(f,'utf8'));}catch{return null;}};
const pad=n=>String(n).padStart(2,'0');
// Local time (the PC runs on Romania time) with its UTC offset, e.g. 2026-11-06T14:00:00+02:00.
export function isoLocal(d){const o=-d.getTimezoneOffset(),s=o>=0?'+':'-',a=Math.abs(o);return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00${s}${pad(Math.floor(a/60))}:${pad(a%60)}`;}
const dayKey=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;

export function readReleases(){
 const root=projectDir();if(!existsSync(join(root,'release.py')))throw new Error('Nu găsesc proiectul Leo (release.py) la '+root+'. Setează LEO_PROJECT_DIR în .env.');
 const order=readJson(join(root,'release_order.json'))||{};const today=dayKey(clock());const prio=order.priority||[];
 const eps=[];
 for(const name of readdirSync(root)){const m=/^v(\d+)$/.exec(name);if(!m)continue;const rel=readJson(join(root,name,'release.json'));if(!rel)continue;
  const hold=order.hold_until?.[name];const res={};for(const[k,v]of Object.entries(KIND)){const r=readJson(join(root,name,v.result));if(r)res[k]={id:r.video_id,publishAt:r.publishAt||null,privacy:r.privacy};}
  eps.push({episode:name,n:Number(m[1]),status:rel.status,title:readJson(join(root,name,'meta.json'))?.title||null,held:hold&&today<hold?hold:null,why:order.why?.[name]||null,
   steps:Object.fromEntries(Object.entries(rel.steps||{}).filter(([,v])=>v?.done).map(([k,v])=>[k,(v.time||'').slice(0,16)])),youtube:res});}
 eps.sort((a,b)=>{const pa=prio.includes(a.episode)?prio.indexOf(a.episode):prio.length,pb=prio.includes(b.episode)?prio.indexOf(b.episode):prio.length;return pa-pb||a.n-b.n;});
 return {root,eps};
}
// Times already taken on YouTube (scheduled or uploaded), from every episode's result files and steps.
function taken(eps,kind){const out=[];for(const e of eps){const r=e.youtube[kind];const t=r?.publishAt||e.steps[KIND[kind].step];if(t){const d=new Date(t);if(!isNaN(d))out.push(d);}}return out;}
function slotProblem(when,used){
 const same=used.filter(d=>dayKey(d)===dayKey(when));if(same.length>=PER_DAY)return `deja ${same.length} pe ${dayKey(when)} (maxim ${PER_DAY}/zi)`;
 const near=used.find(d=>Math.abs(d-when)<GAP_H*3600e3);if(near)return `prea aproape de altul programat la ${isoLocal(near)} (minim ${GAP_H} h)`;return null;
}
export function nextSlot(kind,eps,from=clock()){const used=taken(eps,kind);
 for(let i=0;i<15;i++){for(const h of KIND[kind].slots){const d=new Date(from.getFullYear(),from.getMonth(),from.getDate()+i,h,0,0);if(d-from<30*60e3)continue;if(!slotProblem(d,used))return d;}}return null;}
const lockFile=root=>join(root,'social','locks','youtube.lock');
const stopped=root=>existsSync(join(root,'social','STOP'));

export async function releaseQueue(){
 const {root,eps}=readReleases();
 const pending=k=>eps.filter(e=>e.status==='ready'&&!e.held&&!e.steps[KIND[k].step]&&!e.youtube[k]&&(k==='long'||e.steps.yt_long||e.youtube.long));
 const lock=existsSync(lockFile(root))?readJson(lockFile(root))||{by:'necunoscut'}:null;
 const ns=k=>{const d=nextSlot(k,eps);return d?isoLocal(d):null;};
 return {source:'Leo pipeline (release.json, release_order.json)',retrievedAt:new Date().toISOString(),stop:stopped(root),youtubeLock:lock,
  nextFreeSlot:{long:ns('long'),short:ns('short')},
  readyForLong:pending('long').map(e=>({episode:e.episode,title:e.title})),readyForShort:pending('short').map(e=>({episode:e.episode,title:e.title})),
  held:eps.filter(e=>e.held&&e.status==='ready').map(e=>({episode:e.episode,until:e.held,why:e.why})).slice(0,25),
  scheduledOrPublished:eps.filter(e=>e.youtube.long||e.youtube.short).map(e=>({episode:e.episode,title:e.title,long:e.youtube.long?.publishAt||(e.youtube.long?'publicat':null),short:e.youtube.short?.publishAt||(e.youtube.short?'publicat':null)})),
  rules:'Maxim 2 video lungi + 2 Shorts pe zi, la minim 3 h; lung 14:00/18:00, Short 17:00/21:00; Short-ul unui episod după video-ul lung; episoadele „held” așteaptă data; fără re-upload; social/STOP oprește tot.'};
}

let busy=false;
export async function publishYoutube({episode,kind='long',publishAt}={},ctx={}){
 if(!KIND[kind])throw new Error('kind trebuie să fie "long" sau "short".');
 if(busy)throw new Error('Altă publicare YouTube rulează acum în oraș. Încearcă după ce se termină.');
 busy=true;let locked=false;const {root,eps}=readReleases();
 try{
  if(stopped(root))throw new Error('Există social/STOP: publicarea pe toate platformele este oprită de Mario.');
  const k=KIND[kind];
  const pool=eps.filter(e=>e.status==='ready'&&!e.held&&!e.steps[k.step]&&!e.youtube[kind]&&(kind==='long'||e.steps.yt_long||e.youtube.long));
  const ep=episode?eps.find(e=>e.episode===String(episode).toLowerCase()):pool[0];
  if(!ep)throw new Error(episode?`Episodul ${episode} nu are release.json.`:`Niciun episod gata pentru ${k.label}.`);
  if(ep.status!=='ready')throw new Error(`${ep.episode} are statusul „${ep.status}”, nu „ready”.`);
  if(ep.held)throw new Error(`${ep.episode} este ținut până la ${ep.held}${ep.why?' ('+ep.why+')':''}.`);
  if(ep.steps[k.step]||ep.youtube[kind])throw new Error(`${ep.episode}: ${k.label} a fost deja încărcat; nu se reîncarcă.`);
  if(kind==='short'&&!(ep.steps.yt_long||ep.youtube.long))throw new Error(`${ep.episode}: Short-ul iese după video-ul lung al episodului.`);
  const used=taken(eps,kind);let when;
  if(publishAt){when=new Date(publishAt);if(isNaN(when))throw new Error('publishAt nu este o dată validă (ex. 2026-11-06T14:00:00+02:00).');
   if(when-clock()<20*60e3)throw new Error('publishAt trebuie să fie la cel puțin 20 de minute în viitor.');if(when-clock()>14*864e5)throw new Error('publishAt poate fi cel mult 14 zile în viitor.');
   const p=slotProblem(when,used);if(p)throw new Error(`Ora aleasă nu respectă ritmul: ${p}.`);}
  else{when=nextSlot(kind,eps);if(!when)throw new Error('Nu există niciun slot liber în următoarele 14 zile.');}
  const lf=lockFile(root);
  if(existsSync(lf)){const age=(Date.now()-statSync(lf).mtimeMs)/3600e3;const who=readJson(lf)?.by||'necunoscut';
   throw new Error(`Contul YouTube este ocupat de „${who}” (social/locks/youtube.lock${age>LOCK_STALE_H?`, vechi de ${Math.round(age)} h; probabil rămas blocat, Mario îl poate șterge`:''}).`);}
  writeFileSync(lf,JSON.stringify({by:'agent-town'+(ctx.agent?':'+ctx.agent:''),at:new Date().toISOString()}),{flag:'wx'});locked=true;
  const at=isoLocal(when);
  const up=await runner(python(),[k.script,ep.episode,channelId(),'--publish-at',at],{cwd:root,timeout:45*60e3});
  const result=readJson(join(root,ep.episode,k.result));
  if(!result?.video_id){const why=(up.stderr||up.stdout||'').trim().split(/\r?\n/).slice(-4).join(' · ').slice(0,400);throw new Error(`Încărcarea ${k.label} pentru ${ep.episode} nu a reușit: ${why||'fără mesaj'}.`);}
  const url='https://youtu.be/'+result.video_id;
  const rec=await runner(python(),['release.py',ep.episode,'step',k.step,'--url',url,'--time',isoLocal(clock()),'--note',`Agent Town${ctx.agent?' ('+ctx.agent+')':''}: privat, public la ${at}`],{cwd:root,timeout:120e3});
  return {source:'YouTube Data API prin pipeline-ul Leo (upload_long / youtube_upload_short)',episode:ep.episode,title:ep.title,kind,url,videoId:result.video_id,publishAt:at,
   status:`încărcat privat; YouTube îl face public la ${at}`,recorded:rec.code===0?'înregistrat în release.json':`ATENȚIE: nu s-a putut scrie în release.json (${(rec.stderr||rec.stdout).trim().slice(0,200)})`,
   remaining:kind==='short'?'Setează „Related video” în YouTube Studio înainte de ora publicării (nu există API pentru asta).':'Short-ul episodului poate fi programat după acest video.'};
 }finally{if(locked){try{unlinkSync(lockFile(root));}catch{}}busy=false;}
}
