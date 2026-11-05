import test from 'node:test';
import assert from 'node:assert/strict';
import {agents} from '../src/agents.mjs';
import {BUILDINGS,MEETING_POINTS,CEO_START,HALL,HALL_FRONT,OBSTACLES,PROPS,CODE_PROPS,VILLAGE_ENTRY,worldPoint,isWalkable,findPath,smoothPath,pixelPoint,homeOf} from '../public/village-layout.js';

test('every agent lives in exactly one painted building; Alex runs the Town Hall',()=>{
 assert.equal(BUILDINGS.length,12);assert.equal(new Set(BUILDINGS.map(b=>b.id)).size,12);
 for(const a of agents)assert.equal(BUILDINGS.filter(b=>b.owner===a.id).length,1,a.id);
 assert.equal(homeOf('alex').id,'townhall');assert.ok(BUILDINGS.some(b=>b.id==='mario'));
});

test('each front door connects through its yard to the plaza without leaving paths',()=>{
 assert.ok(isWalkable(CEO_START.x,CEO_START.y));
 for(const b of BUILDINGS){const door=worldPoint(...b.door);assert.ok(isWalkable(door.x,door.y),b.id+' door');
  const route=smoothPath(door,findPath(door,MEETING_POINTS[0]));assert.ok(route.length>0,b.id+' route');
  let prev=door;for(const p of route){for(let i=1;i<=20;i++){const x=prev.x+(p.x-prev.x)*i/20,y=prev.y+(p.y-prev.y)*i/20;assert.ok(isWalkable(x,y),b.id+' leaves the path');}prev=p;}}
 const entry=worldPoint(...VILLAGE_ENTRY);assert.ok(findPath(entry,worldPoint(...BUILDINGS.find(b=>b.id==='townhall').door)).length>0,'newcomers reach the Town Hall');
 for(const id of ['mario','alex']){const p=worldPoint(...HALL_FRONT[id]);assert.ok(isWalkable(p.x,p.y),id+' waits in front of the Town Hall');}
});

test('roofs, fountain, benches and placed props are never walkable',()=>{
 const p=worldPoint(768,575);assert.equal(isWalkable(p.x,p.y),false);
 for(const b of BUILDINGS){const q=worldPoint((b.bounds[0]+b.bounds[2])/2,b.bounds[1]+20);assert.equal(isWalkable(q.x,q.y),false,b.id);}
 for(const r of OBSTACLES){const q=worldPoint((r[0]+r[2])/2,(r[1]+r[3])/2);assert.equal(isWalkable(q.x,q.y),false,'furniture '+r);}
 for(const prop of [...PROPS,...CODE_PROPS]){const q=worldPoint(prop.x,prop.y);assert.equal(isWalkable(q.x,q.y),false,'prop on a path: '+(prop.sprite||prop.kind)+' '+prop.x+','+prop.y);}
 const r=worldPoint(768,575),q=pixelPoint(r.x,r.y);assert.equal(q.x,768);assert.equal(q.y,575);
});

test('Town Hall table has 12 chairs, Mario at the head and a unique seat for everyone',()=>{
 assert.equal(HALL.seats.length,12);assert.equal(HALL.seats[0].role,'head');assert.equal(HALL.assignment.mario,0);
 const seats=Object.values(HALL.assignment);assert.equal(new Set(seats).size,seats.length);
 for(const a of agents)assert.ok(HALL.assignment[a.id]!==undefined,a.id+' has a chair');
 assert.ok(!seats.includes(11),'the foot chair stays free for interview candidates');
});

test('every house door can reach every other door (no unreachable targets)',()=>{
 for(const a of BUILDINGS)for(const b of BUILDINGS){if(a===b)continue;assert.ok(findPath(worldPoint(...a.door),worldPoint(...b.door)).length>0,a.id+' -> '+b.id);}
});
