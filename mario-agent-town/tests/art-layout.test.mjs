import test from 'node:test';
import assert from 'node:assert/strict';
import {agents} from '../src/agents.mjs';
import {BUILDINGS,MEETING_POINTS,CEO_START,worldPoint,isWalkable,findPath,pixelPoint} from '../public/village-layout.js';
test('painted map registers exactly ten agent homes, a CEO manor and Town Hall',()=>{assert.equal(BUILDINGS.length,12);assert.equal(new Set(BUILDINGS.map(b=>b.id)).size,12);for(const a of agents)assert.ok(BUILDINGS.some(b=>b.id===a.id));assert.ok(BUILDINGS.some(b=>b.id==='mario'));assert.ok(BUILDINGS.some(b=>b.id==='townhall'));});
test('every agent home has a walkable path to the central meeting plaza',()=>{assert.ok(isWalkable(CEO_START.x,CEO_START.y));for(const a of agents){const gate=worldPoint(...BUILDINGS.find(b=>b.id===a.id).gate);assert.ok(isWalkable(gate.x,gate.y),a.id+' gate');const route=findPath(gate,MEETING_POINTS[0]);assert.ok(route.length>0,a.id+' route');for(const p of route)assert.ok(isWalkable(p.x,p.y),a.id+' path leaves the path');}});
test('painting coordinates round-trip and roofs/fountain are not walkable',()=>{const p=worldPoint(768,575);const q=pixelPoint(p.x,p.y);assert.equal(q.x,768);assert.equal(q.y,575);assert.equal(isWalkable(p.x,p.y),false);for(const b of BUILDINGS){const p=worldPoint((b.bounds[0]+b.bounds[2])/2,(b.bounds[1]+b.bounds[3])/2);assert.equal(isWalkable(p.x,p.y),false,b.id);}});
