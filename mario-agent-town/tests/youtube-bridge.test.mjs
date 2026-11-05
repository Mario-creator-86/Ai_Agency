import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {fernetDecrypt,setUnwrap,setYoutubeFetcher,myChannel,myAnalytics,listChannels} from '../src/youtube-bridge.mjs';
// Vector produced by Python's cryptography.Fernet, the library the studio uses.
const V={"key": "My7He-gC7u2j3EPMJCzUReHWNRQkA6ozlZlgxj3wJ-Y=", "token": "gAAAAABq7L8NJjy7rc4frTruclDMFpzpuxcBPCB-91eOE396TQuxJ7Y50PsOMvXawovA_CH_n0E7InFgDZv6ow-i5j6-qmDlF_YwbeFBCP3KbXlOd4pzEjlu5RQUOW91OY5sP576stEFj1-sdeh9dSkPY0MaRIlPIQ=="};
test('decrypts tokens written by the studio (Python Fernet) and rejects tampering',()=>{
 assert.deepEqual(JSON.parse(fernetDecrypt(V.key,V.token)),{client_secret:'cs-test',refresh_token:'rt-test'});
 const bad=V.token.slice(0,-6)+(V.token.at(-6)==='A'?'B':'A')+V.token.slice(-5);assert.throws(()=>fernetDecrypt(V.key,bad),/altă cheie|format/);
 assert.throws(()=>fernetDecrypt('short',V.token),/format/);});
function studio(){const dir=mkdtempSync(join(tmpdir(),'studio-'));mkdirSync(join(dir,'data'));const db=new DatabaseSync(join(dir,'data','studio.db'));
 db.exec("CREATE TABLE youtube_connection(id TEXT,name TEXT,client_id TEXT,encrypted_secrets TEXT,secret_fields TEXT,status TEXT,remote_channel_id TEXT,remote_channel_title TEXT,granted_scopes TEXT)");
 const ins=db.prepare('INSERT INTO youtube_connection VALUES (?,?,?,?,?,?,?,?,?)');ins.run('a','Nexus','cid',V.token,'[]','CONNECTED','UCnexus','NEXUS CURIOSITY','https://www.googleapis.com/auth/youtube.readonly');
 ins.run('b','Inside','cid',V.token,'[]','CONNECTED','UCleo','Leo Explains','https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly');ins.run('c','Old','cid',V.token,'[]','AUTH_REQUIRED','UCold','Old','');db.close();writeFileSync(join(dir,'data','studio.credentials.key'),'wrapped');return dir;}
test('reads only connected channels, refreshes a token and calls read-only endpoints',async()=>{const dir=studio();process.env.AMN_STUDIO_DIR=dir;const calls=[];
 setUnwrap(async()=>V.key);setYoutubeFetcher(async(url,opt={})=>{const u=String(url);calls.push({u,method:opt.method||'GET',body:String(opt.body||'')});
  if(u.includes('oauth2.googleapis.com/token'))return new Response(JSON.stringify({access_token:'at',expires_in:3600}));
  if(u.includes('/channels?'))return new Response(JSON.stringify({items:[{snippet:{title:'Leo Explains'},statistics:{subscriberCount:'1234',viewCount:'99999',videoCount:'12'},contentDetails:{relatedPlaylists:{uploads:'UU1'}}}]}));
  if(u.includes('/playlistItems?'))return new Response(JSON.stringify({items:[{contentDetails:{videoId:'v1'}}]}));
  if(u.includes('/videos?'))return new Response(JSON.stringify({items:[{id:'v1',snippet:{title:'How AI works',publishedAt:'2026-11-01T10:00:00Z'},statistics:{viewCount:'500',likeCount:'20',commentCount:'3'},contentDetails:{duration:'PT5M'},status:{privacyStatus:'public'}}]}));
  if(u.includes('youtubeanalytics')){if(u.includes('dimensions=video'))return new Response(JSON.stringify({columnHeaders:[{name:'video'},{name:'views'}],rows:[['v1',500]]}));return new Response(JSON.stringify({columnHeaders:[{name:'views'},{name:'subscribersGained'},{name:'subscribersLost'}],rows:[[700,30,4]]}));}
  return new Response('{}',{status:404});});
 try{assert.deepEqual(listChannels().map(c=>c.channel),['NEXUS CURIOSITY','Leo Explains']);
  const ch=await myChannel({});assert.equal(ch.channel,'Leo Explains','Leo Explains is the default');assert.equal(ch.subscribers,1234);assert.equal(ch.latestVideos[0].views,500);
  const an=await myAnalytics({channel:'leo explains',days:28});assert.equal(an.totals.netSubscribers,26);assert.equal(an.topVideos[0].title,'How AI works');
  await assert.rejects(()=>myAnalytics({channel:'NEXUS CURIOSITY'}),/dreptul de statistici/);await assert.rejects(()=>myChannel({channel:'Altceva'}),/nu e conectat/);
  const token=calls.filter(c=>c.u.includes('oauth2'));assert.equal(token.length,1,'access token is cached');assert.match(token[0].body,/grant_type=refresh_token/);
  assert.ok(calls.every(c=>c.method==='GET'||c.u.includes('oauth2')),'only reads, never writes to YouTube');assert.ok(!JSON.stringify([ch,an]).includes('rt-test')&&!JSON.stringify([ch,an]).includes('cs-test'),'secrets never appear in results');}
 finally{setUnwrap(async()=>{throw new Error('x');});setYoutubeFetcher((...a)=>fetch(...a));delete process.env.AMN_STUDIO_DIR;rmSync(dir,{recursive:true,force:true});}});
test('an expired authorization is explained to Mario',async()=>{const dir=studio();process.env.AMN_STUDIO_DIR=dir;setUnwrap(async()=>V.key);setYoutubeFetcher(async()=>new Response(JSON.stringify({error:'invalid_grant'}),{status:400}));
 try{await assert.rejects(()=>myChannel({}),/Reconectează canalul în studio/);}finally{setYoutubeFetcher((...a)=>fetch(...a));delete process.env.AMN_STUDIO_DIR;rmSync(dir,{recursive:true,force:true});}});
