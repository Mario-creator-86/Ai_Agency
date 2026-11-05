// Read access to the Leo Explains stats dashboard that already runs on this PC (stickman_series/dashboard,
// http://127.0.0.1:8010). The dashboard collects YouTube, TikTok, Facebook, Instagram and Pinterest
// statistics every 15 minutes and returns statistics only (no tokens). If it is not running, the town
// starts it with the dashboard's own launcher (start_dashboard.pyw --nobrowser), which only starts the
// stats server. The town never changes the dashboard's data.
import {existsSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {spawn} from 'node:child_process';

const DEFAULT_LAUNCHER='C:\\Users\\mario\\PyCharmMiscProject\\Market Signals V9\\stickman_series\\dashboard\\start_dashboard.pyw';
const DEFAULT_PYTHONW='E:\\AI Acency\\Autonomous_AI_Studio_Documentation_v5_ECONOMY_TREASURY_VENDORSHOP\\.venv\\Scripts\\pythonw.exe';
export const dashboardUrl=()=>(process.env.LEO_DASHBOARD_URL||'http://127.0.0.1:8010').replace(/\/$/,'');
export const launcherPath=()=>process.env.LEO_DASHBOARD_LAUNCHER||DEFAULT_LAUNCHER;

let fetcher=(...a)=>fetch(...a);
let launcher=()=>new Promise((resolve,reject)=>{
 if(process.platform!=='win32')return reject(new Error('Dashboard-ul Leo rulează doar pe PC-ul lui Mario (Windows).'));
 const file=launcherPath();if(!existsSync(file))return reject(new Error('Nu găsesc start_dashboard.pyw la '+file+' (setează LEO_DASHBOARD_LAUNCHER în .env).'));
 const py=process.env.LEO_DASHBOARD_PYTHONW||(existsSync(DEFAULT_PYTHONW)?DEFAULT_PYTHONW:'pythonw.exe');
 try{const child=spawn(py,[file,'--nobrowser'],{cwd:dirname(file),detached:true,stdio:'ignore',windowsHide:true});child.on('error',reject);child.unref();setTimeout(resolve,300);}catch(e){reject(e);}
});
export function setDashboardFetcher(fn){fetcher=fn;}
export function setDashboardLauncher(fn){launcher=fn;starting=null;}

async function call(path,{method='GET',timeout=15000}={}){
 const ctl=new AbortController();const t=setTimeout(()=>ctl.abort(),timeout);
 try{const r=await fetcher(dashboardUrl()+path,{method,signal:ctl.signal,headers:{Accept:'application/json'}});const body=await r.json().catch(()=>({}));return {status:r.status,body};}
 finally{clearTimeout(t);}
}
const alive=async()=>{try{const r=await call('/api/summary',{timeout:4000});return r.status===200;}catch{return false;}};

let starting=null;
// Makes sure the dashboard answers; starts it once if it is down and waits up to ~25 s.
export async function ensureDashboard(){
 if(await alive())return {running:true,started:false};
 if(!starting)starting=(async()=>{await launcher();for(let i=0;i<25;i++){await new Promise(r=>setTimeout(r,1000));if(await alive())return true;}throw new Error('Dashboard-ul Leo nu a pornit în 25 s.');})().finally(()=>{starting=null;});
 await starting;return {running:true,started:true};
}

// Keeps the payload small enough for a model: drops thumbnails, caps lists, keeps numbers and titles.
export function compactSummary(x,depth=0){
 if(Array.isArray(x))return x.slice(0,depth>2?8:15).map(v=>compactSummary(v,depth+1));
 if(x&&typeof x==='object'){const o={};for(const[k,v]of Object.entries(x)){if(/^thumb|^caption$/.test(k)||v===null||v===undefined||v==='')continue;o[k]=compactSummary(v,depth+1);}return o;}
 if(typeof x==='string'&&x.length>300)return x.slice(0,300)+'…';
 return x;
}

const PLATFORMS=['youtube','tiktok','facebook','instagram','pinterest'];
export async function leoDashboard({view='summary',platform,id,refresh=false}={}){
 await ensureDashboard();
 const out={source:'Leo dashboard ('+dashboardUrl()+')',retrievedAt:new Date().toISOString()};
 if(refresh){const r=await call('/api/refresh',{method:'POST',timeout:120000});out.refresh=r.body?.ok?'statistici actualizate acum':(r.body?.error||'actualizarea nu a pornit');}
 if(view==='history'){const p=PLATFORMS.includes(platform)?platform:'youtube';const r=await call('/api/history?platform='+p);if(r.status!==200)throw new Error(r.body?.error||'istoric indisponibil');const rows=Array.isArray(r.body)?r.body:[];return {...out,platform:p,points:rows.length,history:rows.slice(-40)};}
 if(view==='video_history'){if(!id)throw new Error('video_history cere "id" (id-ul video-ului din summary).');const p=PLATFORMS.includes(platform)?platform:'youtube';const r=await call('/api/video_history?platform='+p+'&id='+encodeURIComponent(id));if(r.status!==200)throw new Error(r.body?.error||'istoric indisponibil');const rows=Array.isArray(r.body)?r.body:[];return {...out,platform:p,id,history:rows.slice(-40)};}
 const r=await call('/api/summary');if(r.status!==200)throw new Error(r.body?.error||'rezumat indisponibil');
 const s=r.body||{};
 if(view==='videos'){let v=Array.isArray(s.videos)?s.videos:[];if(platform)v=v.filter(x=>x.platform===platform);v=[...v].sort((a,b)=>(b.views||0)-(a.views||0));
  return {...out,last_refresh:s.last_refresh,count:v.length,videos:v.slice(0,25).map(x=>compactSummary({platform:x.platform,kind:x.kind,id:x.id,title:x.title,published:x.published,views:x.views,likes:x.likes,comments:x.comments,shares:x.shares,like_rate:x.like_rate,views_24h:x.views_24h,series:x.series,url:x.url}))};}
 const pick=platform&&PLATFORMS.includes(platform)?{[platform]:s[platform]}:Object.fromEntries(PLATFORMS.filter(p=>s[p]).map(p=>[p,s[p]]));
 return {...out,last_refresh:s.last_refresh,next_refresh:s.next_refresh,status:s.status,...compactSummary(pick),analytics_totals:s.analytics?.totals,analytics_note:s.analytics?.note,monetization:compactSummary(s.monetization),alerts:compactSummary(s.alerts),series:compactSummary((s.series||[]).slice(0,12)),videos_count:(s.videos||[]).length,hint:'view "videos" = top video-uri pe toate platformele; "history" = evoluția canalului; "video_history" cu id'};
}

export async function dashboardStatus(){try{const r=await ensureDashboard();return {ok:true,...(r.started?{note:'pornit acum de oraș'}:{})};}catch(e){return {ok:false,error:String(e.message||e).slice(0,160)};}}
// Called at town start-up so the agents find the dashboard already running.
export function keepDashboardAlive(){if(process.platform!=='win32'||process.env.LEO_DASHBOARD_DISABLE)return;ensureDashboard().catch(e=>console.log('Dashboard Leo: '+e.message));}
