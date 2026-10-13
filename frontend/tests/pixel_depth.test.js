import test from 'node:test';
import assert from 'node:assert/strict';
import { depthOrder, insidePolygon, foliagePixel, streetLighting } from '../src/pixel_depth.js';
import { PIXEL_LAYOUT } from '../src/pixel_desks.js';

test('ground depth orders rear walkers, pets, bicycle, clock, traffic and foreground independently of facing',()=>{
 const source=[{id:'car',depth:590,direction:-1},{id:'clock',depth:587},{id:'walker-front',depth:575,direction:1},{id:'dog',depth:572},{id:'walker-back',depth:570,direction:-1},{id:'bicycle',depth:579},{id:'foreground',depth:640}];
 const before=structuredClone(source);
 assert.deepEqual(depthOrder(source).map(a=>a.id),['walker-back','dog','walker-front','bicycle','clock','car','foreground']);
 assert.deepEqual(source,before);
 assert.deepEqual(depthOrder(source.map(a=>({...a,direction:-(a.direction||1)}))).map(a=>a.id),depthOrder(source).map(a=>a.id));
});
test('depth ties are stable by identity while indoor floors do not depend on roster order',()=>{
 const objects=[{id:'b',depth:229},{id:'z',depth:531},{id:'a',depth:229},{id:'c',depth:375}];
 assert.deepEqual(depthOrder(objects).map(a=>a.id),['a','b','c','z']);
 assert.deepEqual(depthOrder(objects.reverse()).map(a=>a.id),['a','b','c','z']);
});
test('foreground uses bounded object contours with transparent road gaps, not a rectangular left-edge exclusion',()=>{
 const regions=PIXEL_LAYOUT.depth.foreground_regions;
 assert.equal(regions.filter(r=>r.material==='foliage').length,3);
 for(const r of regions){assert.ok(r.polygon.length>=4);assert.ok(r.polygon.every(([x,y])=>x>=0&&x<=960&&y>=518&&y<=640));}
 assert.equal(regions.some(r=>insidePolygon(450,580,r.polygon)),false,'open road is always clear');
 assert.equal(insidePolygon(25,580,regions[0].polygon),true);
 assert.equal(foliagePixel(35,64,52),true);assert.equal(foliagePixel(234,207,147),true);
 assert.equal(foliagePixel(131,123,145),false,'purple road cannot become a plant');
 assert.equal(foliagePixel(70,69,88),false,'road shadows remain holes');
});

test('street actors follow ambient light while vehicle lamps can remain emissive',()=>{
 assert.equal(streetLighting({daylight:1}),'none');
 assert.equal(streetLighting({daylight:0}),'brightness(0.43) saturate(0.82)');
 assert.notEqual(streetLighting({daylight:.5}),streetLighting({daylight:0}));
});
