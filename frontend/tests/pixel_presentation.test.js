import test from 'node:test';
import assert from 'node:assert/strict';
import {PRESENTATION,presentationAction,presentationLive,SeatedPhysics} from '../src/pixel_presentation.js';
import {RoomPhysics} from '../src/pixel_room_life.js';
import {PIXEL_LAYOUT} from '../src/pixel_desks.js';

const agent={id:'p',lifecycle:'ACTIVE',runtime_state:'IDLE',version:4};
const plan={agent_id:'p',lifecycle:'ACTIVE',runtime_state:'IDLE',version:4,phase_ms:0,cycle:PRESENTATION.cycles.IDLE};
test('fresh backend HTTP policies bridge websocket reconnection without authorizing stale or future data',()=>{
 assert.equal(presentationLive({data:'fresh',socket:'connecting'},10000,10001),true);
 assert.equal(presentationLive({data:'fresh',socket:'closed'},10000,46000),false);
 assert.equal(presentationLive({data:'fresh',socket:'closed'},10000,9999),false);
 assert.equal(presentationLive({data:'stale',socket:'open'},10000,10001),false);
 assert.equal(presentationLive({data:'fresh',socket:'open'},0,10001),true);
 assert.equal(presentationLive({data:'fresh',socket:'closed'},0,10001),false);
});
test('only a fresh matching backend version can authorize coffee or monitor power',()=>{
 const actions=new Set();for(let t=0;t<53500;t+=500)actions.add(presentationAction(plan,agent,t,10000,10001).action);
 assert.ok(actions.has('coffee')&&actions.has('hair')&&actions.has('screen_off')&&actions.has('screen_on'));
 for(const a of [{...agent,version:5},{...agent,runtime_state:'WORKING'},{...agent,lifecycle:'PAUSED'}])assert.equal(presentationAction(plan,a,20000,10000,10001),null);
 assert.equal(presentationAction(plan,agent,20000,10000,50000),null);
});
test('spring pose transitions stay bounded, settle, keep contacts, and freeze while paused',()=>{
 const physics=new SeatedPhysics(),seat=PIXEL_LAYOUT.stations[0].seating;let previous;
 for(let t=0;t<24000;t+=16){const action=t<4000?'look':t<8000?'coffee':t<12000?'hair':t<16000?'type':'think';
  const p=physics.frame('p',{action,elapsed:t,animate:true},seat);
  assert.ok(p.weights.every(v=>v>=0&&v<=1));assert.ok(Math.abs(p.weights.reduce((a,b)=>a+b,0)-1)<1e-9);
  assert.ok(Math.abs(p.head)<=PRESENTATION.physics.head_limit_radians);assert.ok(Math.abs(p.lean)<=1);
  assert.deepEqual(p.feet,seat.contacts.feet);assert.deepEqual(p.chair,seat.contacts.chair);
  for(const [x,y] of p.feet){assert.ok(y>=seat.floor_plane.far_y&&y<=seat.floor_plane.near_y);
   assert.ok(x>=seat.floor_plane.min_x&&x<=seat.floor_plane.max_x);
   assert.ok(seat.solids.every(s=>x<s.x||x>s.x+s.w||y<s.y||y>s.y+s.h));}
  if(previous)assert.ok(p.weights.every((w,i)=>Math.abs(w-previous.weights[i])<.08),'no frame-sized pose jump');previous=p;
 }
 assert.deepEqual(physics.frame('p',{action:'look',elapsed:90000,animate:false},seat),previous);
});
test('wind-driven loose paper lands on a known surface, cannot pass cabinet tops, and remains bounded',()=>{
 const physics=new RoomPhysics(),positions=PIXEL_LAYOUT.stations.map((p,i)=>({...p,id:String(i)}));let sawFlight=false,sawLanding=false;
 for(let t=0;t<190000;t+=16){const frame=physics.frame(t,{available:true,windKph:22},positions);
  assert.ok(frame.papers.length<=8);
  for(const p of frame.papers){const seat=positions[Number(p.id)].seating;
   sawFlight ||= !p.settled;sawLanding ||= p.settled&&p.surface==='floor';
   assert.ok(p.y<=seat.floor_y);assert.ok(p.x>=seat.floor_plane.min_x&&p.x<=seat.floor_plane.max_x);
   assert.ok(Number.isFinite(p.angle));}
 }
 assert.ok(sawFlight&&sawLanding);
 const missing=new RoomPhysics();for(let t=0;t<100000;t+=250)assert.ok(missing.frame(t,{available:false,windKph:90},positions).papers.every(p=>p.settled&&p.surface==='desk'));
});
