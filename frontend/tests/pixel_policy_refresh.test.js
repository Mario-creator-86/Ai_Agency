import test from 'node:test';
import assert from 'node:assert/strict';
import {OfficeEngine} from '../src/pixel_office.js';
import {PRESENTATION} from '../src/pixel_presentation.js';

function setup(t,fetchPresentation){
 const original={window:globalThis.window,document:globalThis.document};
 t.mock.timers.enable({apis:['setTimeout','Date'],now:100000});
 globalThis.window={setTimeout:globalThis.setTimeout};globalThis.document={hidden:false};
 t.after(()=>{globalThis.window=original.window;globalThis.document=original.document;});
 const agent={id:'p',lifecycle:'ACTIVE',runtime_state:'IDLE',version:1};
 const plan=a=>({agent_id:a.id,lifecycle:a.lifecycle,runtime_state:a.runtime_state,version:a.version,phase_ms:0,cycle:a.lifecycle==='ACTIVE'?PRESENTATION.cycles[a.runtime_state]:[]});
 const snapshot=a=>({schema:1,agents:[plan(a)],media:{local:[],youtube:[]}});
 const e=Object.assign(Object.create(OfficeEngine.prototype),{
  agents:[agent],positions:[],pixelLayout:undefined,page:0,parked:false,replay:false,lifeElapsed:0,
  presentation:new Map([['p',plan(agent)]]),presentationReceived:Date.now(),presentationAt:0,presentationPending:false,
  presentationDirty:false,presentationRevision:'',presentationRefreshTimer:0,presentationEpoch:0,
  options:{dataLive:()=>true,presentationReadable:()=>true,fetchPresentation},screens:{setMedia(){}},
  draw(){},schedule(){},syncHits(){},renderPages(){},renderRoster(){},currentWeather:()=>({windKph:0}),
 });
 e.setAgents([agent]);e.presentationDirty=false;
 clearTimeout(e.presentationRefreshTimer);e.presentationRefreshTimer=0;
 return {e,agent,plan,snapshot};
}
const flush=async()=>{await Promise.resolve();await Promise.resolve();};

test('in-place committed record changes refresh matching policy immediately; identical/reordered paints do not fetch',async t=>{
 let reads=0;const {e,agent,snapshot}=setup(t,async()=>{reads++;return snapshot(agent);});
 Object.assign(agent,{version:2,runtime_state:'WORKING'});e.setAgents([agent]);
 assert.equal(e.motionFor(agent).animate,false,'no invented gesture while backend policy is mismatched');
 t.mock.timers.tick(PRESENTATION.state_refresh_debounce_ms-1);await flush();assert.equal(reads,0);
 t.mock.timers.tick(1);await flush();assert.equal(reads,1);
 assert.ok(e.motionFor(agent).authorized&&e.motionFor(agent).animate);assert.equal(e.motionFor(agent).action,'type');
 for(let i=0;i<20;i++)e.setAgents([agent]);t.mock.timers.tick(1000);await flush();assert.equal(reads,1);
});

test('a delayed old HTTP response cannot animate a newer event; one serialized follow-up reads the current version',async t=>{
 let resolve,reads=0;const {e,agent,snapshot}=setup(t,()=>{reads++;return reads===1?new Promise(r=>resolve=r):Promise.resolve(snapshot(agent));});
 Object.assign(agent,{version:2,runtime_state:'WORKING'});e.setAgents([agent]);
 t.mock.timers.tick(PRESENTATION.state_refresh_debounce_ms);const old=snapshot(agent);
 Object.assign(agent,{version:3,runtime_state:'THINKING'});e.setAgents([agent]);
 assert.equal(reads,1);assert.equal(e.presentationPending,true);
 resolve(old);await flush();assert.equal(e.motionFor(agent).authorized,false);assert.equal(e.motionFor(agent).animate,false);
 t.mock.timers.tick(PRESENTATION.state_retry_ms);await flush();assert.equal(reads,2);
 assert.equal(e.motionFor(agent).action,'think');assert.equal(e.presentation.get('p').version,3);
});

test('failed reads retry at the configured bound and never authorize the preceding state',async t=>{
 let reads=0;const {e,agent,snapshot}=setup(t,async()=>{if(++reads===1)throw Error('offline');return snapshot(agent);});
 Object.assign(agent,{version:2,runtime_state:'ERROR'});e.setAgents([agent]);
 t.mock.timers.tick(PRESENTATION.state_refresh_debounce_ms);await flush();assert.equal(e.motionFor(agent).animate,false);
 t.mock.timers.tick(PRESENTATION.state_retry_ms-1);await flush();assert.equal(reads,1);
 t.mock.timers.tick(1);await flush();assert.equal(reads,2);assert.ok(e.motionFor(agent).authorized);assert.equal(e.motionFor(agent).action,'frustrated');
});

test('owner/visibility/replay guards refuse reads and a late response from a retired owner context',async t=>{
 let resolve,reads=0;const {e,agent,snapshot}=setup(t,()=>{reads++;return new Promise(r=>resolve=r);});
 for(const block of ['parked','replay','hidden','unreadable']){
  e.parked=block==='parked';e.replay=block==='replay';document.hidden=block==='hidden';e.options.presentationReadable=()=>block!=='unreadable';
  await e.refreshPresentation(true);assert.equal(reads,0);
 }
 e.parked=false;e.replay=false;document.hidden=false;e.options.presentationReadable=()=>true;
 const pending=e.refreshPresentation(true);const received=e.presentationReceived;
 e.presentationEpoch++;e.parked=true;resolve(snapshot({...agent,version:9}));await pending;
 assert.equal(e.presentation.get('p').version,1);assert.equal(e.presentationReceived,received);assert.equal(e.presentationRefreshTimer,0);
});

test('paused, unknown and expired policies do not animate; state labels remain derived from the actual record',async t=>{
 const {e,agent,snapshot}=setup(t,async()=>snapshot(agent));
 for(const state of ['WORKING','THINKING','REVIEWING','ERROR','BLOCKED']){
  Object.assign(agent,{runtime_state:state,version:agent.version+1});await e.refreshPresentation(true);assert.ok(e.motionFor(agent).animate);
 }
 agent.lifecycle='PAUSED';agent.version++;await e.refreshPresentation(true);
 assert.equal(e.motionFor(agent).mode,'PAUSED');assert.equal(e.motionFor(agent).monitor,'off');assert.equal(e.motionFor(agent).animate,false);
 agent.lifecycle='ACTIVE';agent.runtime_state='UNKNOWN';agent.version++;await e.refreshPresentation(true);assert.equal(e.motionFor(agent).animate,false);
 agent.runtime_state='WORKING';agent.version++;await e.refreshPresentation(true);
 t.mock.timers.tick(PRESENTATION.valid_ms+1);assert.equal(e.motionFor(agent).authorized,false);assert.equal(e.motionFor(agent).animate,false);
});
