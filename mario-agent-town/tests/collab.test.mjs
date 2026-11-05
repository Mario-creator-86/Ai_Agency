import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,existsSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Store} from '../src/store.mjs';
import {Runtime} from '../src/runtime.mjs';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function setup(){const dir=mkdtempSync(join(tmpdir(),'agent-town-collab-'));const store=new Store(dir);return {dir,store,close:()=>{store.close();rmSync(dir,{recursive:true,force:true});}};}
async function drained(rt){for(let i=0;i<300;i++){if(!rt.active&&!rt.queue.length)return;await sleep(10);}throw new Error('Runtime did not drain');}
const real=(store,...ids)=>{for(const id of ids)store.set('agent:'+id,{provider:'ollama',model:'fake',enabled:true,lastAuto:0});};

test('a meeting needs two real brains and never invents speech for Demo agents',()=>{const f=setup();const rt=new Runtime(f.store,f.dir,()=>{},()=>{throw Error('no call');});try{assert.throws(()=>rt.startMeeting({topic:'Strategie'}),/cel puțin doi/);}finally{rt.close();f.close();}});

test('meeting: every participant speaks, the chair writes a strategy and assigns tasks',async()=>{const f=setup();real(f.store,'alex','maria','sofia');const calls=[];
 const provider=async(p,m,messages)=>{const sys=messages[0].content;calls.push(sys.slice(0,20));if(sys.includes('Conduci ședința'))return JSON.stringify({reply:'Am decis.',strategy:'## Decizii\n- Video săptămânal',tasks:[{agent:'maria',title:'Scrie scenariul'},{agent:'victor',title:'Nu participă'}]});return JSON.stringify({reply:'Propunerea mea.',remember:'Am promis un draft'});};
 const rt=new Runtime(f.store,f.dir,()=>{},provider);try{await sleep(5);const m=rt.startMeeting({topic:'Creștere YouTube'});assert.deepEqual(m.participants.sort(),['alex','maria','sofia']);
  // the strategy's tasks start immediately, so stop the follow-up work after the meeting closes
  for(let i=0;i<300&&f.store.meetings()[0].status!=='done';i++)await sleep(10);rt.stop();await drained(rt);
  const done=f.store.meetings()[0];assert.equal(done.status,'done');assert.equal(done.transcript.length,6,'3 agents × 2 rounds');assert.ok(done.artifact);
  const tasks=f.store.tasks();assert.equal(tasks.filter(t=>t.title==='Scrie scenariul').length,1);assert.equal(tasks.filter(t=>t.agent==='victor').length,0,'non-participants get no tasks');
  assert.ok(f.store.memories('maria').some(x=>x.includes('draft')));assert.equal(f.store.messages().filter(m=>m.channel==='meeting'&&m.sender==='sofia').length,2);}finally{rt.close();f.close();}});

test('encounters: first meeting of the day takes notes for both, second one walks by',()=>{const f=setup();f.store.task('maria','Thumbnail nou');const rt=new Runtime(f.store,f.dir);try{
 const a=rt.encounter('maria','sofia');assert.equal(a.mode,'notes');assert.ok(f.store.memories('sofia')[0].includes('Thumbnail nou'));assert.ok(f.store.memories('maria')[0].includes('Sofia'));
 assert.equal(rt.encounter('sofia','maria').talked,false);}finally{rt.close();f.close();}});

test('hiring: Alex proposes, nobody is hired without yes, yes creates folder, notes and a first task',async()=>{const f=setup();const rt=new Runtime(f.store,f.dir,()=>{},()=>{throw Error('demo must not call');});try{await sleep(5);
 rt.proposeCandidate('maria','prea multe sarcini');await drained(rt);const c=f.store.staff()[0];assert.equal(c.status,'candidate');assert.equal(c.profile.source,'template');
 assert.equal(f.store.hiredStaff().length,0);assert.equal(rt.proposeCandidate('maria','din nou').pending,true,'one open candidate per director');
 rt.hire(c.id,true);const dir=join(f.dir,'workspaces',c.id);for(const file of ['IDENTITY.md','INSTRUCTIONS.md','NOTES.md'])assert.ok(existsSync(join(dir,file)),file);
 assert.match(readFileSync(join(dir,'INSTRUCTIONS.md'),'utf8'),/echipa lui Maria/);assert.equal(f.store.hiredStaff()[0].director,'maria');assert.ok(f.store.tasks().some(t=>t.agent===c.id));
 assert.throws(()=>rt.hire(c.id,true),/indisponibil/);rt.stop();}finally{rt.close();f.close();}});

test('rejecting a candidate hires nobody',async()=>{const f=setup();const rt=new Runtime(f.store,f.dir);try{await sleep(5);rt.proposeCandidate('irina','buget');await drained(rt);const c=f.store.staff()[0];rt.hire(c.id,false);assert.equal(f.store.staffMember(c.id).status,'rejected');assert.equal(f.store.hiredStaff().length,0);}finally{rt.close();f.close();}});

test('room chat: everyone with a brain answers once, Demo agents are reported not faked',async()=>{const f=setup();real(f.store,'ana','radu');let n=0;const rt=new Runtime(f.store,f.dir,()=>{},async()=>JSON.stringify({reply:'Răspuns '+(++n)}));try{await sleep(5);
 assert.equal(rt.say('all','Bună dimineața',['ana','radu','maria','mario']).queued,2);await drained(rt);const said=f.store.messages().filter(m=>m.channel==='meeting');assert.deepEqual(said.map(m=>m.sender),['mario','ana','radu']);}finally{rt.close();f.close();}});

import {TEAMS,agentsFor} from '../src/agents.mjs';
import {BUILDINGS,HALL} from '../public/village-layout.js';
test('three team versions reuse the same characters with distinct jobs, houses and chairs',()=>{
 assert.deepEqual(Object.keys(TEAMS),['v1','v2','v3']);
 for(const t of Object.keys(TEAMS)){const list=agentsFor(t);assert.equal(new Set(list.map(a=>a.id)).size,list.length);assert.equal(new Set(list.map(a=>a.role)).size,list.length,t+' roles are unique');
  for(const a of list){assert.ok(BUILDINGS.some(b=>b.owner===a.id),a.id+' keeps a house');assert.ok(HALL.assignment[a.id]!==undefined,a.id+' keeps a chair');assert.ok(a.mission.length>80);}}
 assert.equal(agentsFor('v2').length,9,'the trading firm has nine agents');assert.equal(agentsFor('v2').find(a=>a.id==='alex').role,'Director de investiții & coordonator');
 assert.ok(agentsFor('v2').some(a=>a.role==='Manager de risc'));assert.equal(agentsFor('v3').length,10);
});
test('a team keeps its own data and its charter reaches every prompt',async()=>{const dir=mkdtempSync(join(tmpdir(),'agent-town-team-'));const v2=new Store(join(dir,'v2'),'v2');const seen=[];
 v2.set('agent:david',{provider:'ollama',model:'fake',enabled:true,lastAuto:0});const rt=new Runtime(v2,join(dir,'v2'),()=>{},async(p,m,messages)=>{seen.push(messages[0].content);return JSON.stringify({reply:'BLOCATĂ — DATE INSUFICIENTE',actions:[]});});
 try{await sleep(5);rt.enqueue({agent:'david',text:'Verifică propunerea',channel:'david',depth:0});await drained(rt);assert.match(seen[0],/Manager de risc/);assert.match(seen[0],/BLOCATĂ — DATE INSUFICIENTE/);assert.match(seen[0],/Tăcerea nu este aprobare/);
  assert.equal(v2.snapshot().agents.some(a=>a.id==='maria'),false,'Maria is not in the trading firm');
  const v1=new Store(join(dir,'v1'),'v1');assert.equal(v1.messages().some(m=>m.text.includes('Verifică propunerea')||m.sender==='david'),false,'chats do not leak across versions');v1.close();}
 finally{rt.close();v2.close();rmSync(dir,{recursive:true,force:true});}});
