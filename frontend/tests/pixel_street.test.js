import test from 'node:test';
import assert from 'node:assert/strict';
import { streetFrame } from '../src/pixel_life.js';
import { normalizeWeather } from '../src/hq_weather.js';
import { ACTORS } from '../src/pixel_actor_atlas.js';
const clear=normalizeWeather({available:true,condition:'clear'});

test('street travel has walking, cycling and driving speeds independent of rendering cadence',()=>{
 const a=streetFrame(2000,clear,false),b=streetFrame(3000,clear,false);
 for(let i=0;i<4;i++)assert.ok(Math.abs((b.people[i].x-a.people[i].x)*a.people[i].direction-36.129032258)<1e-6);
 assert.ok(Math.abs(b.bicycle.x-a.bicycle.x-74.666666667)<1e-6);
 assert.equal(a.car.x-b.car.x,140);
 assert.ok(Math.abs(streetFrame(2000+1000/24,clear,false).people[0].x-a.people[0].x-36.129032258/24)<1e-6);
});
test('every walker reaches both edges, wrapping only when its whole silhouette is outside',()=>{
 for(let id=0;id<4;id++){
  const route=[];
  for(let t=0;t<=62000;t+=100)route.push(streetFrame(t,clear,false).people[id].x);
  assert.ok(route.some(x=>x<0));assert.ok(route.some(x=>x>960));
  assert.ok(route.some(x=>x>0&&x<100));assert.ok(route.some(x=>x>860&&x<960));
  for(let i=1;i<route.length;i++)if(Math.abs(route[i]-route[i-1])>10)assert.ok(Math.min(route[i],route[i-1])<-60&&Math.max(route[i],route[i-1])>1020);
 }
 const variants=new Set();let before=streetFrame(0,clear,false).car;
 for(let t=50;t<=64000;t+=50){const c=streetFrame(t,clear,false).car;variants.add(c.variant);
  if(c.variant!==before.variant)assert.ok(c.x>1020&&before.x<-60,'vehicle changes model entirely off screen');before=c;
 }
 assert.equal(variants.size,4);
});
test('both cats cover full patrols with brief rests instead of spending long intervals blocked',()=>{
 for(let id=0;id<2;id++){
  const xs=[],poses=new Set();let still=0,longest=0,walks=0,previous;
  for(let t=0;t<76000;t+=50){const c=streetFrame(t,clear,false).cats[id];xs.push(c.x);poses.add(c.pose);if(c.pose==='walk')walks++;
   if(previous){assert.ok(Math.abs(c.x-previous.x)<=1.01);still=c.x===previous.x?still+50:0;longest=Math.max(longest,still);}previous=c;
  }
  assert.equal(Math.max(...xs)-Math.min(...xs),id===0?280:320);
  assert.ok(longest<=3000);assert.ok(walks/xs.length>.83);
  assert.deepEqual([...poses].sort(),['groom','sit','stretch','walk']);
 }
});
test('all four cars have full independent profiles with wheels registered inside the silhouette',()=>{
 assert.equal(ACTORS.atlases.cars.rows.length,4);
 for(const row of ACTORS.atlases.cars.rows){const f=row.frames[0];
  assert.ok(f.width/f.height>2&&f.width/f.height<2.7,'uniform side-view car proportions');
  assert.equal(f.wheels.length,2);
  assert.ok(f.wheels[0].x<.3&&f.wheels[1].x>.7);
  for(const w of f.wheels)assert.ok(w.y>.7&&w.y<.88&&w.rim>0&&w.rim<w.tyre&&w.x-w.tyre*f.height/f.width>0&&w.x+w.tyre*f.height/f.width<1);
 }
});
