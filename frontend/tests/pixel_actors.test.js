import test from 'node:test';
import assert from 'node:assert/strict';
import { streetFrame } from '../src/pixel_life.js';
import { normalizeWeather } from '../src/hq_weather.js';
import { pixelPen } from '../src/pixel_art.js';
import { characterProfile, characterMotion, drawSeatedPerson } from '../src/pixel_people.js';
import { drawPedestrian, drawBicycle, drawCat, drawDog } from '../src/pixel_town_people.js';
const clear=normalizeWeather({available:true,condition:'clear'});

test('cats alternate walking, sitting, grooming and stretching without teleporting between activities',()=>{
  const poses=new Set();let last=streetFrame(0,clear,true).cat;
  for(let t=50;t<112000;t+=50){
    const c=streetFrame(t,clear,true).cat;poses.add(c.pose);
    assert.ok(Math.abs(c.x-last.x)<=1,`continuous cat route at ${t}`);
    if(c.pose!=='walk'&&c.pose===last.pose)assert.equal(c.x,last.x);
    assert.equal(c.y,last.y);last=c;
  }
  assert.deepEqual([...poses].sort(),['groom','sit','stretch','walk']);
  assert.equal(streetFrame(0,clear,true).cats.length,2);
});

test('eight walk and pedal phases remain independent, with a decorative dog attached to its walker',()=>{
  assert.equal(new Set(Array.from({length:8},(_,i)=>streetFrame(i*150,clear,true).people[0].step)).size,8);
  assert.equal(new Set(Array.from({length:8},(_,i)=>streetFrame(i*140,clear,true).bicycle.step)).size,8);
  for(const t of [0,7000,19000,78000]){
    const f=streetFrame(t,clear,true),p=f.people[2];
    assert.equal(f.dog.x-p.x,29*p.direction);assert.equal(f.dog.direction,p.direction);
    assert.equal(f.dog.y-p.y,2);assert.ok(!('agent_id' in f.dog));
  }
});

function canvasCalls(){
 const calls=[];return {calls,save(){},restore(){},translate(){},scale(){},
  fillRect(x,y,w,h){calls.push([x,y,w,h,this.fillStyle]);}};
}

test('integer contours draw shaped limbs and transparent wheel rings without fractional pixels',()=>{
  const c=canvasCalls(),p=pixelPen(c);
  p.line(0.4,0.4,8.7,4.2,'#abcdef',2);p.ellipse(15,10,7,7,'#abcdef',1);p.polygon([[0,0],[6,1],[3,9]],'#abcdef');
  assert.ok(c.calls.every(a=>a.slice(0,4).every(Number.isInteger)));
  const ring=canvasCalls();pixelPen(ring).ellipse(0,0,9,9,'#abcdef',2);
  assert.ok(!ring.calls.some(([x,y])=>x===0&&y===0),'wheel interior stays transparent');
});

test('town cast draws distinguishable silhouettes and groom/pedal frames actually differ',()=>{
  const paint=(draw,actor)=>{const c=canvasCalls();draw(c,actor);return c.calls;};
  const f=streetFrame(0,clear,false);
  const walker=paint(drawPedestrian,f.people[0]),cycle=paint(drawBicycle,f.bicycle),cat=paint(drawCat,f.cat),dog=paint(drawDog,f.dog);
  for(const rows of [walker,cycle,cat,dog])assert.ok(rows.length>150,'shaded raster silhouette is present');
  assert.notDeepEqual(cycle,paint(drawBicycle,{...f.bicycle,step:4}));
  assert.notDeepEqual(paint(drawCat,{...f.cat,pose:'groom',step:0}),paint(drawCat,{...f.cat,pose:'groom',step:2}));
  assert.notDeepEqual(walker,cat);assert.notDeepEqual(cat,dog);
});

test('detailed seated frames retain identity and seat footprint across real states',()=>{
 const agent={id:'detailed-employee',role_name:'LeadResearcher',runtime_state:'IDLE',lifecycle:'ACTIVE'};
 const bible={employee_id:agent.id,palette_json:{hair:'#456789',shirt:'#dedabc',coat:'#81968a',skin:'#c69273'},face_hair_desc:'silver spectacles',props_desc:''};
 const p=characterProfile(agent,bible),before=structuredClone(agent),a=canvasCalls();
 drawSeatedPerson(a,p,characterMotion(agent,1000,true),260,229,1.5,false,'back');
 assert.ok(a.calls.some(row=>row[4]===bible.palette_json.hair));
 assert.ok(a.calls.every(([x,y,w,h])=>x>=0&&x+w<=48&&y>=0&&y+h<=60));
 assert.deepEqual(agent,before);assert.equal(p.skin,bible.palette_json.skin);
 const b=canvasCalls();drawSeatedPerson(b,p,characterMotion({...agent,runtime_state:'THINKING'},1000,true),260,229,1.5,false,'back');
 assert.notDeepEqual(a.calls,b.calls);
});
