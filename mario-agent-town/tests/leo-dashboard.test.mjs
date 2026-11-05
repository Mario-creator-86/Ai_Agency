import test from 'node:test';
import assert from 'node:assert/strict';
import {leoDashboard,setDashboardFetcher,setDashboardLauncher,compactSummary} from '../src/leo-dashboard.mjs';
import {DATA_TOOLS} from '../src/datatools.mjs';
import {toolsFor} from '../src/agents.mjs';

const summary={last_refresh:'2026-11-05T19:00:00Z',status:{youtube:{ok:true}},youtube:{channel:{followers:38,views:9000}},tiktok:{channel:{followers:12}},analytics:{totals:{views:9341}},
 videos:[{platform:'youtube',id:'a',title:'Low',views:5,thumb:'/thumbs/a.jpg'},{platform:'tiktok',id:'b',title:'High',views:900,caption:'x'}],series:[],monetization:{platforms:{}},alerts:[]};
const res=(status,body)=>({status,json:async()=>body});

test('dashboard is started once when down, then read; only statistics reach the agent',async()=>{
 let up=false,launches=0;const calls=[];
 setDashboardLauncher(async()=>{launches++;up=true;});
 setDashboardFetcher(async(url,opt)=>{calls.push(opt.method+' '+url);if(!up)throw new Error('ECONNREFUSED');if(url.includes('/api/summary'))return res(200,summary);if(url.includes('/api/history'))return res(200,[{ts:1,followers:30},{ts:2,followers:38}]);return res(404,{error:'not found'});});
 const s=await leoDashboard({});assert.equal(launches,1);assert.equal(s.youtube.channel.followers,38);assert.equal(s.tiktok.channel.followers,12);assert.equal(s.analytics_totals.views,9341);
 const v=await leoDashboard({view:'videos'});assert.equal(v.videos[0].title,'High');assert.ok(!JSON.stringify(v).includes('thumbs'));
 const h=await leoDashboard({view:'history',platform:'tiktok'});assert.equal(h.platform,'tiktok');assert.equal(h.history.length,2);
 await leoDashboard({});assert.equal(launches,1,'not relaunched while running');
 assert.ok(calls.every(c=>c.includes('127.0.0.1:8010')));assert.ok(!calls.some(c=>c.startsWith('POST')),'no refresh unless asked');
 await assert.rejects(()=>leoDashboard({view:'video_history'}),/id/);
});

test('refresh is a single POST to the dashboard and its rate limit is reported, not hidden',async()=>{
 setDashboardLauncher(async()=>{});
 setDashboardFetcher(async(url,opt)=>opt.method==='POST'?res(429,{ok:false,error:'wait 40 s between refreshes'}):res(200,summary));
 const s=await leoDashboard({refresh:true});assert.match(s.refresh,/wait 40 s/);
});

test('compaction drops thumbnails and caps long lists',()=>{const c=compactSummary({thumb:'x',list:Array.from({length:50},(_,i)=>i)});assert.equal(c.thumb,undefined);assert.equal(c.list.length,15);});

test('every V3 agent and V1 Maria can read the dashboard',()=>{
 assert.ok(DATA_TOOLS.leo_dashboard);for(const id of ['maria','alex','radu','elena','sofia','victor','david','tudor','irina','ana'])assert.ok(toolsFor('v3',id).includes('leo_dashboard'),id);
 assert.ok(toolsFor('v1','maria').includes('leo_dashboard'));assert.ok(!toolsFor('v2','victor').includes('leo_dashboard'));
});
