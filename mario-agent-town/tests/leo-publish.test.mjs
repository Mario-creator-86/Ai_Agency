import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {releaseQueue,publishYoutube,setPublishRunner,setPublishClock,isoLocal} from '../src/leo-publish.mjs';
import {toolsFor} from '../src/agents.mjs';

function project(){
 const root=mkdtempSync(join(tmpdir(),'leo-'));writeFileSync(join(root,'release.py'),'#');mkdirSync(join(root,'social','locks'),{recursive:true});
 const ep=(n,status,steps={},extra={})=>{mkdirSync(join(root,n));writeFileSync(join(root,n,'release.json'),JSON.stringify({status,steps}));writeFileSync(join(root,n,'meta.json'),JSON.stringify({title:'Title '+n}));for(const[f,v]of Object.entries(extra))writeFileSync(join(root,n,f),JSON.stringify(v));};
 ep('v20','ready',{yt_long:{done:true,time:'2026-11-03T12:04'}},{'youtube_result.json':{video_id:'OLD20',publishAt:'2026-11-06T14:00:00+02:00'}});
 ep('v44','ready');ep('v46','ready');ep('v47','ready');ep('v24','published',{yt_long:{done:true,time:'2026-11-05T01:48'}});
 writeFileSync(join(root,'release_order.json'),JSON.stringify({hold_until:{v47:'2099-01-01'},why:{v47:'later'},priority:[]}));
 process.env.LEO_PROJECT_DIR=root;process.env.LEO_PYTHON='py';return root;
}
// Fake pipeline: writes the result file like upload_long.py does and records the release.py calls.
function fakeRunner(root,calls,{fail=false}={}){return async(cmd,args,{cwd})=>{calls.push(args);assert.equal(cwd,root);assert.ok(existsSync(join(root,'social','locks','youtube.lock')),'lock held during the upload');
 if(args[0]==='release.py'){const f=join(root,args[1],'release.json');const d=JSON.parse(readFileSync(f,'utf8'));d.steps[args[3]]={done:true,url:args[5],time:args[7]};writeFileSync(f,JSON.stringify(d));return {code:0,stdout:'ok',stderr:''};}
 if(fail)return {code:1,stdout:'',stderr:'preflight failed: not uploading'};
 const file=args[0]==='upload_long.py'?'youtube_result.json':'short_youtube_result.json';writeFileSync(join(root,args[1],file),JSON.stringify({video_id:'NEW'+args[1],privacy:'private',publishAt:args[4]}));return {code:0,stdout:'uploaded',stderr:''};};}

test('queue lists ready, held and scheduled episodes and the next free slot',async()=>{
 project();setPublishClock(()=>new Date(2026,10,6,9,0));
 const q=await releaseQueue();assert.deepEqual(q.readyForLong.map(e=>e.episode),['v44','v46']);assert.deepEqual(q.readyForShort.map(e=>e.episode),['v20']);
 assert.equal(q.held[0].episode,'v47');assert.equal(q.nextFreeSlot.long,isoLocal(new Date(2026,10,6,18,0)),'14:00 is taken by v20');assert.equal(q.stop,false);
});

test('publishing uses the pipeline script, schedules the next free slot, records it and frees the lock',async()=>{
 const root=project();setPublishClock(()=>new Date(2026,10,6,9,0));const calls=[];setPublishRunner(fakeRunner(root,calls));
 const r=await publishYoutube({},{agent:'ana'});assert.equal(r.episode,'v44');assert.equal(r.url,'https://youtu.be/NEWv44');assert.equal(r.publishAt,isoLocal(new Date(2026,10,6,18,0)));
 assert.deepEqual(calls[0],['upload_long.py','v44','UCsJC65Up_k9TtKHA1eaEK3Q','--publish-at',r.publishAt]);assert.equal(calls[1][0],'release.py');assert.match(calls[1].join(' '),/v44 step yt_long --url https:\/\/youtu\.be\/NEWv44/);
 assert.ok(!existsSync(join(root,'social','locks','youtube.lock')),'lock removed');
 // day is now full (v20 14:00 + v44 18:00): the next long goes to tomorrow 14:00
 const r2=await publishYoutube({},{agent:'maria'});assert.equal(r2.episode,'v46');assert.equal(r2.publishAt,isoLocal(new Date(2026,10,7,14,0)));
 await assert.rejects(()=>publishYoutube({episode:'v44'}),/deja încărcat/);
 await assert.rejects(()=>publishYoutube({},{}),/Niciun episod/);
});

test('guards: STOP, held episode, busy lock, cadence, Short before long, failed upload',async()=>{
 let root=project();setPublishClock(()=>new Date(2026,10,6,9,0));const calls=[];setPublishRunner(fakeRunner(root,calls));
 await assert.rejects(()=>publishYoutube({episode:'v47'}),/ținut până la 2099-01-01/);
 await assert.rejects(()=>publishYoutube({episode:'v46',kind:'short'}),/după video-ul lung/);
 await assert.rejects(()=>publishYoutube({episode:'v44',publishAt:'2026-11-06T15:00:00+02:00'}),/prea aproape|3 h/);
 await assert.rejects(()=>publishYoutube({episode:'v44',publishAt:'2026-11-06T09:05:00+02:00'}),/20 de minute/);
 writeFileSync(join(root,'social','locks','youtube.lock'),'{"by":"leo-publish-noon"}');await assert.rejects(()=>publishYoutube({}),/leo-publish-noon/);
 writeFileSync(join(root,'social','STOP'),'');await assert.rejects(()=>publishYoutube({}),/STOP/);
 assert.equal(calls.length,0,'nothing was uploaded');
 root=project();setPublishRunner(fakeRunner(root,calls,{fail:true}));await assert.rejects(()=>publishYoutube({}),/preflight failed/);
 assert.ok(!existsSync(join(root,'social','locks','youtube.lock')));assert.ok(!calls.some(c=>c[0]==='release.py'),'a failed upload is never recorded');
});

test('Short of a released episode goes to a Short slot',async()=>{
 const root=project();setPublishClock(()=>new Date(2026,10,6,9,0));setPublishRunner(fakeRunner(root,[]));
 const r=await publishYoutube({kind:'short'});assert.equal(r.episode,'v20');assert.equal(r.publishAt,isoLocal(new Date(2026,10,6,17,0)));assert.match(r.remaining,/Related video/);
});

test('only the showrunner and distribution can publish; the producer can read the queue',()=>{
 for(const id of ['maria','ana'])assert.ok(toolsFor('v3',id).includes('publish_youtube'),id);
 for(const id of ['alex','radu','elena','sofia','victor','david','tudor','irina'])assert.ok(!toolsFor('v3',id).includes('publish_youtube'),id);
 assert.ok(toolsFor('v3','alex').includes('release_queue'));assert.ok(!toolsFor('v1','maria').includes('publish_youtube'));
});
