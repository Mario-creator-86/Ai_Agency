import test from 'node:test';
import assert from 'node:assert/strict';
import {PHRASES,streetClock,StreetLife,randomSource,randomVehicle,VEHICLE_MODELS,depthSortedTraffic,pixelDisc,refreshVehicle} from '../src/street_life.js';
import {makeTraffic,updateTraffic} from '../src/office_engine.js';
const clock=h=>streetClock(new Date(Date.UTC(2026,8,10,h-3)));
test('local clock dims at night and sharply reduces the street population',()=>{
 assert.equal(clock(3).daylight,0);assert.equal(clock(12).daylight,1);
 assert.equal(clock(3).people,3);assert.ok(clock(12).people>clock(3).people);
 assert.equal(clock(3).birds,false);assert.equal(clock(12).birds,true);
 assert.ok(clock(6).daylight>0&&clock(6).daylight<1);
});
test('seeded randomness is reproducible for QA and covers every vehicle silhouette',()=>{
 const a=randomSource(123),b=randomSource(123);
 for(let i=0;i<20;i++) assert.equal(a(),b());
 const rng=randomSource(321), kinds=new Set();
 for(let i=0;i<1000;i++) kinds.add(randomVehicle(rng).kind);
 assert.equal(kinds.size,VEHICLE_MODELS.length);
});
test('near traffic is always painted after far traffic without mutating simulation order',()=>{
 const near={laneOffset:.78},far={laneOffset:.34}; const original=[near,far];
 assert.deepEqual(depthSortedTraffic(original),[far,near]);assert.equal(original[0],near);
});
test('pixel wheel has circular scanlines, narrow poles and a broad equator',()=>{
 const rows=[];pixelDisc({fillRect:(...r)=>rows.push(r)},10,10,7,'black');
 assert.equal(rows.length,15);assert.equal(rows[0][2],1);assert.equal(rows[7][2],15);
 assert.deepEqual(rows.map(r=>r[2]),rows.map(r=>r[2]).reverse());
});
test('ambient phrases are shuffled without repeats until the deck is exhausted',()=>{
 const scene=new StreetLife(2,1200,clock(12));const lines=Array.from({length:PHRASES.length},()=>scene.phrase());
 assert.equal(new Set(lines).size,PHRASES.length);assert.notEqual(scene.phrase(),lines.at(-1));
});
test('ordinary night passersby remain possible; population is bounded and transitions without teleporting',()=>{
 const night=new StreetLife(5,1200,clock(3));assert.equal(night.people.length,3);
 assert.ok(clock(3).activities.walk>clock(3).activities.run);
 const day=new StreetLife(8,1200,clock(12)); const kinds=new Set();
 for(let i=0;i<20000;i++) {day.update(.05,clock(12));day.people.forEach(p=>kinds.add(p.activity));assert.ok(day.people.length<=clock(12).people);}
 for(const kind of ['walk','commute','friends','shopping']) assert.ok(kinds.has(kind),kind);
 for(let i=0;i<20000;i++) day.update(.05,clock(3));
 assert.ok(day.people.length<=clock(3).people);
});
test('random vehicle replacement preserves lane gaps across the wrap seam',()=>{
 const rng=randomSource(56),cars=makeTraffic(84);
 for(let i=0;i<20000;i++) {
 const before=cars.map(c=>c.x);updateTraffic(cars,1200,.05);
 cars.forEach((c,j)=>{if(Math.abs(c.x-before[j])>600) refreshVehicle(c,cars,1200,rng,clock(12));});
 for(const car of cars) for(const other of cars) {
 if(car===other||car.dir!==other.dir) continue;
 const delta=((other.x-car.x)%1500+1500)%1500;
 assert.ok(delta-car.style.w>=23.9, 'positive bumper gap after RNG replacement');
 }
 }
});

const when=(day,hour)=>streetClock(new Date(Date.UTC(2026,8,day,hour-3)));
test('morning runners, workday commuters and weekend leisure have different probabilities',()=>{
 const morning=when(7,7),work=when(7,10),saturday=when(12,10);
 assert.ok(morning.activities.run>work.activities.run);
 assert.ok(work.activities.commute>saturday.activities.commute*5);
 assert.ok(saturday.activities.friends>work.activities.friends||!work.activities.friends);
 for(const c of [morning,work,saturday]) assert.ok(c.activities.walk>0);
});
test('weekend nightlife crosses midnight but Sunday evening and Monday night settle down',()=>{
 const tue=when(8,1),sat=when(12,1),sun=when(13,1),mon=when(14,1);
 assert.ok(sat.people>tue.people&&sun.people>mon.people);
 assert.ok(sat.traffic>tue.traffic);
 assert.ok(sat.activities.party>0&&sat.activities.walk>0);
 assert.ok(when(11,21).activities.party>when(13,21).activities.party);
 const before=streetClock(new Date(Date.UTC(2026,8,11,20,59,59)));
 assert.ok(Math.abs(before.traffic-when(12,0).traffic)<.001);
});
test('traffic mix follows purpose: more buses at commute time and taxis after nights out',()=>{
 const rng=randomSource(90),sample=c=>{
 const result={};for(let i=0;i<6000;i++){const k=randomVehicle(rng,c).kind;result[k]=(result[k]||0)+1;}return result;};
 const rush=sample(when(7,10)),night=sample(when(12,1));
 assert.ok(rush.bus>300);assert.equal(night.bus,undefined);
 assert.ok(night.taxi>rush.taxi*2);
});
test('friends spawn together with matching direction and speed, respecting capacity',()=>{
 const c=when(12,21);c.activities={friends:1};c.people=12;
 const scene=new StreetLife(112,1200,c);
 const groups=Map.groupBy(scene.people.filter(p=>p.groupId!==null),p=>p.groupId);
 for(const members of groups.values()){
 assert.ok(members.length>=2&&members.length<=4);
 assert.ok(members.every(p=>p.dir===members[0].dir&&p.speed===members[0].speed));
 const delta=members[1].x-members[0].x;scene.update(.05,c);
 assert.ok(Math.abs((members[1].x-members[0].x)-delta)<.001);
 }
 assert.equal(scene.people.length,12);
});
test('all minutes of a week keep ordinary walkers, bounded populations and valid weights',()=>{
 for(let day=7;day<14;day++)for(let minute=0;minute<1440;minute++){
 const c=streetClock(new Date(Date.UTC(2026,8,day,-3,minute)));
 assert.ok(c.people>=3&&c.people<=17&&c.activities.walk>0);
 assert.ok(c.traffic>=0&&c.traffic<=1);
 assert.ok(Object.values(c.activities).every(w=>Number.isFinite(w)&&w>=0));
 }
});

test('late phone dialogue omits closed-shop errands and daytime bus claims',()=>{
 const scene=new StreetLife(3,1200,when(8,1));
 for(let i=0;i<100;i++) assert.ok(!/(MAGAZIN|BIBLIOTECA|BRUTARIE|AUTOBUZ)/.test(scene.phrase(true)));
});

test('groups cannot occupy every slot, including on party nights',()=>{
 for(let seed=1;seed<100;seed++) {
  const scene=new StreetLife(seed,1200,when(12,1));
  assert.ok(scene.people.filter(p=>p.groupId!==null).length<=3);
  assert.ok(scene.people.some(p=>p.activity==='walk'||p.activity==='phone'||p.activity==='dog'||p.activity==='cat'||p.activity==='run'||p.activity==='smoke'||p.activity==='angry'));
 }
});

test('a small group is possible on an ordinary quiet night without removing every passerby',()=>{
 const c=when(8,1);c.activities={friends:1};
 const scene=new StreetLife(1,1200,c);
 assert.equal(scene.people.filter(p=>p.groupId!==null).length,2);
 assert.equal(scene.people.filter(p=>p.activity==='walk').length,1);
});
