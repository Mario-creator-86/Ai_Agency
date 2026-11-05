// Read-only bridge to the YouTube channels already connected in the AMN-AI studio on this PC.
// The studio keeps the OAuth client secret and refresh token encrypted with Fernet; the Fernet key
// is wrapped with Windows DPAPI for the Owner's account. The town unwraps it in memory only, asks
// Google for a short-lived access token and calls read-only endpoints. Nothing secret is written
// to disk, logged, or shown to an AI model, and the upload/manage scopes are never used.
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,existsSync} from 'node:fs';
import {join} from 'node:path';
import {createHmac,createDecipheriv,timingSafeEqual} from 'node:crypto';
import {spawn} from 'node:child_process';

const DEFAULT_STUDIO='E:\\AI Acency\\Autonomous_AI_Studio_Documentation_v5_ECONOMY_TREASURY_VENDORSHOP';
export const studioDir=()=>process.env.AMN_STUDIO_DIR||DEFAULT_STUDIO;
const fromB64url=s=>Buffer.from(String(s).replace(/-/g,'+').replace(/_/g,'/'),'base64');

// Fernet spec: version(0x80) | timestamp(8) | iv(16) | ciphertext | hmac-sha256(32); key = sign(16) | encrypt(16).
export function fernetDecrypt(keyB64,token){
 const key=fromB64url(keyB64);if(key.length!==32)throw new Error('Cheia studioului are un format neașteptat.');
 const data=fromB64url(token);if(data.length<57||data[0]!==0x80)throw new Error('Datele criptate ale studioului au un format neașteptat.');
 const body=data.subarray(0,data.length-32),mac=data.subarray(data.length-32);const expected=createHmac('sha256',key.subarray(0,16)).update(body).digest();
 if(!timingSafeEqual(mac,expected))throw new Error('Conexiunea a fost salvată cu altă cheie decât cea a studioului.');
 const iv=body.subarray(9,25),cipher=body.subarray(25);const d=createDecipheriv('aes-128-cbc',key.subarray(16),iv);return Buffer.concat([d.update(cipher),d.final()]).toString('utf8');
}

// Unwraps the studio key with DPAPI through PowerShell. The key path goes in an environment
// variable, never into the command text.
let unwrap=keyFile=>new Promise((resolve,reject)=>{
 if(process.platform!=='win32')return reject(new Error('Conexiunea YouTube a studioului se poate citi doar pe Windows, cu contul tău.'));
 const script="Add-Type -AssemblyName System.Security;$b=[IO.File]::ReadAllBytes($env:TOWN_STUDIO_KEY);[Convert]::ToBase64String([Security.Cryptography.ProtectedData]::Unprotect($b,$null,'CurrentUser'))";
 const child=spawn('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{env:{...process.env,TOWN_STUDIO_KEY:keyFile},windowsHide:true});let out='',err='';
 const timer=setTimeout(()=>{child.kill();reject(new Error('Deblocarea cheii studioului a durat prea mult.'));},20000);
 child.stdout.on('data',b=>out+=b);child.stderr.on('data',b=>err+=b);child.on('error',e=>{clearTimeout(timer);reject(e);});
 child.on('close',code=>{clearTimeout(timer);if(code!==0)return reject(new Error('Windows nu a putut debloca cheia studioului pentru acest cont.'));
  // DPAPI returns the Fernet key exactly as the studio stored it (url-safe base64 text).
  resolve(Buffer.from(out.trim(),'base64').toString('utf8').trim());});
});
export function setUnwrap(fn){unwrap=fn;fernetKey=null;tokens.clear();}
let fetcher=(...a)=>fetch(...a);export function setYoutubeFetcher(fn){fetcher=fn;tokens.clear();}

let fernetKey=null;const tokens=new Map();
function readConnections(){
 const db=join(studioDir(),'data','studio.db');if(!existsSync(db))throw new Error(`Nu găsesc baza studioului AI Agency (${db}). Setează AMN_STUDIO_DIR în .env.`);
 const conn=new DatabaseSync(db,{readOnly:true});try{return conn.prepare("SELECT id,name,client_id,encrypted_secrets,secret_fields,status,remote_channel_id,remote_channel_title,granted_scopes FROM youtube_connection WHERE status='CONNECTED'").all();}finally{conn.close();}
}
export function listChannels(){return readConnections().map(c=>({channel:c.remote_channel_title||c.name,channelId:c.remote_channel_id,analytics:String(c.granted_scopes||'').includes('yt-analytics.readonly')}));}
function pick(conns,channel){if(!conns.length)throw new Error('Studioul nu are niciun canal YouTube conectat.');if(!channel)return conns.find(c=>/leo/i.test(c.remote_channel_title||''))||conns[0];
 const q=String(channel).toLowerCase();const c=conns.find(c=>[c.remote_channel_title,c.name,c.remote_channel_id].some(v=>String(v||'').toLowerCase()===q))||conns.find(c=>String(c.remote_channel_title||'').toLowerCase().includes(q));
 if(!c)throw new Error(`Canalul „${channel}” nu e conectat. Canale disponibile: ${conns.map(c=>c.remote_channel_title).join(', ')}.`);return c;}
async function accessToken(c){
 const hit=tokens.get(c.id);if(hit&&hit.until>Date.now()+60000)return hit.token;
 if(!fernetKey)fernetKey=await unwrap(join(studioDir(),'data','studio.credentials.key'));
 const secrets=JSON.parse(fernetDecrypt(fernetKey,c.encrypted_secrets));if(!secrets.refresh_token||!secrets.client_secret)throw new Error('Conexiunea canalului din studio nu are acces de lungă durată. Reconectează canalul în studio.');
 const r=await fetcher('https://oauth2.googleapis.com/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({client_id:c.client_id,client_secret:secrets.client_secret,refresh_token:secrets.refresh_token,grant_type:'refresh_token'}),signal:AbortSignal.timeout(20000)});
 const j=await r.json().catch(()=>({}));if(!r.ok||!j.access_token)throw new Error(j.error==='invalid_grant'?'Google a refuzat accesul: autorizarea canalului a expirat sau a fost revocată. Reconectează canalul în studio.':`Google a refuzat tokenul (HTTP ${r.status}).`);
 tokens.set(c.id,{token:j.access_token,until:Date.now()+(Number(j.expires_in)||3000)*1000});return j.access_token;
}
async function gget(url,token){const r=await fetcher(url,{headers:{Authorization:'Bearer '+token},signal:AbortSignal.timeout(20000)});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(`YouTube a răspuns HTTP ${r.status}: ${j.error?.message||''}`.slice(0,300));return j;}
const API='https://www.googleapis.com/youtube/v3';
const day=d=>d.toISOString().slice(0,10);

export async function myChannel({channel}={}){
 const c=pick(readConnections(),channel),t=await accessToken(c);const j=await gget(`${API}/channels?part=snippet,statistics,contentDetails&id=${c.remote_channel_id}`,t);const it=j.items?.[0];if(!it)throw new Error('YouTube nu a returnat canalul.');
 const uploads=it.contentDetails?.relatedPlaylists?.uploads;let videos=[];
 if(uploads){const pl=await gget(`${API}/playlistItems?part=contentDetails&maxResults=15&playlistId=${uploads}`,t);const ids=(pl.items||[]).map(x=>x.contentDetails.videoId).filter(Boolean);
  if(ids.length){const v=await gget(`${API}/videos?part=snippet,statistics,contentDetails,status&id=${ids.join(',')}`,t);videos=(v.items||[]).map(x=>({title:x.snippet.title,published:x.snippet.publishedAt,privacy:x.status?.privacyStatus,duration:x.contentDetails?.duration,views:Number(x.statistics.viewCount)||0,likes:Number(x.statistics.likeCount)||0,comments:Number(x.statistics.commentCount)||0,url:`https://www.youtube.com/watch?v=${x.id}`}));}}
 return {channel:it.snippet.title,channelId:c.remote_channel_id,subscribers:Number(it.statistics.subscriberCount)||0,totalViews:Number(it.statistics.viewCount)||0,videoCount:Number(it.statistics.videoCount)||0,latestVideos:videos,retrievedAt:new Date().toISOString(),source:'YouTube Data API (contul tău, doar citire, prin conexiunea studioului)'};
}
export async function myAnalytics({channel,days=28}={}){
 const c=pick(readConnections(),channel);if(!String(c.granted_scopes||'').includes('yt-analytics.readonly'))throw new Error('Conexiunea canalului nu are dreptul de statistici. Reconectează canalul în studio.');
 const t=await accessToken(c);const n=Math.max(7,Math.min(365,Number(days)||28));const end=new Date(Date.now()-864e5),start=new Date(end-(n-1)*864e5);
 const base=`https://youtubeanalytics.googleapis.com/v2/reports?ids=channel==${c.remote_channel_id}&startDate=${day(start)}&endDate=${day(end)}`;
 const rows=j=>(j.rows||[]).map(r=>Object.fromEntries((j.columnHeaders||[]).map((h,i)=>[h.name,r[i]])));
 const [totals,daily,top,traffic]=await Promise.all([
  gget(`${base}&metrics=views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,likes,comments,shares`,t),
  gget(`${base}&metrics=views,subscribersGained,subscribersLost&dimensions=day&sort=day`,t),
  gget(`${base}&metrics=views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained&dimensions=video&sort=-views&maxResults=10`,t),
  gget(`${base}&metrics=views,estimatedMinutesWatched&dimensions=insightTrafficSourceType&sort=-views`,t)]);
 const topRows=rows(top);let titles={};const ids=topRows.map(r=>r.video).filter(Boolean);
 if(ids.length){const v=await gget(`${API}/videos?part=snippet&id=${ids.join(',')}`,t);titles=Object.fromEntries((v.items||[]).map(x=>[x.id,x.snippet.title]));}
 const tot=rows(totals)[0]||{};
 return {channel:c.remote_channel_title,period:`${day(start)} → ${day(end)} (${n} zile)`,totals:{...tot,netSubscribers:(tot.subscribersGained||0)-(tot.subscribersLost||0)},daily:rows(daily),topVideos:topRows.map(r=>({...r,title:titles[r.video]||r.video})),trafficSources:rows(traffic),retrievedAt:new Date().toISOString(),source:'YouTube Analytics API (doar citire). Datele YouTube Analytics au întârziere de 1-3 zile.',note:'CTR-ul și afișările (impressions) nu sunt disponibile prin acest API; se văd doar în YouTube Studio.'};
}
export async function bridgeStatus(){try{const list=listChannels();if(!list.length)return {ok:false,error:'Studioul nu are canale conectate.'};await accessToken(pick(readConnections()));return {ok:true,channels:list.map(c=>c.channel)};}catch(e){return {ok:false,error:e.message};}}
