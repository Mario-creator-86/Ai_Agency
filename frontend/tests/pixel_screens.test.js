import test from 'node:test';
import assert from 'node:assert/strict';
import {projectScreen,monitorSupport} from '../src/pixel_screens.js';
import {PRESENTATION} from '../src/pixel_presentation.js';

test('inclined monitor content reaches all four physical screen corners without moving its frame',()=>{
 const corners=[[454,465],[483,473],[477,484],[449,476]];
 const transforms=[],clips=[];let polygon=[];
 const ctx={save(){},restore(){},beginPath(){polygon=[];},moveTo(x,y){polygon.push([x,y]);},lineTo(x,y){polygon.push([x,y]);},closePath(){},clip(){clips.push(polygon);},transform(...matrix){transforms.push(matrix);},drawImage(){}};
 projectScreen(ctx,{width:100,height:50},corners);
 assert.equal(transforms.length,2);assert.deepEqual(clips,[[corners[0],corners[1],corners[2]],[corners[0],corners[2],corners[3]]]);
 for(const [i,indices] of [[0,[0,1,2]],[1,[0,2,3]]])for(const j of indices){
  const [x,y]=[[0,0],[100,0],[100,50],[0,50]][j],[a,b,c,d,e,f]=transforms[i];
  assert.ok(Math.abs(a*x+c*y+e-corners[j][0])<1e-9);
  assert.ok(Math.abs(b*x+d*y+f-corners[j][1])<1e-9);
 }
});

test('physical monitor panels clear the desktop and leave a visible support; a submerged panel is refused',()=>{
 for(const monitor of PRESENTATION.monitors.filter(m=>m.housing)){
  const support=monitorSupport(monitor);
  assert.ok(support.desktop-support.bottom>=2,monitor.desk_id);
 }
 const nadia=PRESENTATION.monitors.find(m=>m.desk_id==='desk_accounting');
 assert.ok(nadia.artwork,'the original drafting board must actually be removed');
 assert.equal(nadia.polygon[0][0],nadia.polygon[3][0]);
 assert.equal(nadia.polygon[1][0],nadia.polygon[2][0]);
 assert.ok(Math.abs(nadia.polygon[0][1]-nadia.polygon[1][1])<1,'upright screen, not a tilted drawing surface');
 assert.throws(()=>monitorSupport({polygon:[[0,0],[20,0],[20,11],[0,11]],housing:{desktop_y:10}}),RangeError);
});
