import test from 'node:test';
import assert from 'node:assert/strict';
import { seatedGeometry, poseTarget, StaffPoseTrack } from '../src/pixel_staff_pose.js';
import { ACTORS } from '../src/pixel_actor_atlas.js';
import { PIXEL_LAYOUT } from '../src/pixel_desks.js';

 test('person and chair have one uniform scale, unchanged lower-body proportions and a grounded base', () => {
  for (const asset of [ACTORS.atlases.staff_a, ACTORS.atlases.staff_b]) for (const row of asset.rows) {
    const frame=row.frames[0];
    for (const station of PIXEL_LAYOUT.stations) {
      const p=seatedGeometry(frame,station.x,station.y,60,station.seating);
      assert.equal(p.feetY,station.seating.floor_y);
      assert.ok(Math.abs(p.height-station.seating.ensemble_height*.9)<1e-12,'exactly 10% smaller around the same floor contact');
      assert.ok(Math.abs(p.width/p.height-frame.width/frame.height)<1e-12);
      assert.equal(p.top+p.height,p.feetY);
      assert.equal(p.left+frame.anchor_x*p.scale,station.seating.ensemble_x);
    }
  }
 });
 test('joint motion is continuous through whole cycles and a state transition starts from the last pose', () => {
  const track=new StaffPoseTrack();let last;
  for (let elapsed=0;elapsed<=62000;elapsed+=16) {
    const mode=elapsed<20000?'IDLE':elapsed<40000?'WORKING':'THINKING';
    const p=track.frame('person',{mode,animate:true,elapsed});
    if(last) {assert.ok(Math.abs(p.head-last.head)<.003);assert.ok(Math.abs(p.hand-last.hand)<.009);}
    assert.ok(Math.abs(p.head)<=.075);assert.ok(Math.abs(p.hand)<=.061);last=p;
  }
  assert.deepEqual(track.frame('person',{mode:'PAUSED',animate:false,elapsed:0}),last);
  const previous=track.frame('person',{mode:'IDLE',animate:true,elapsed:62001});
  assert.deepEqual(previous,last,'no jump on a backend state change');
  assert.deepEqual(poseTarget({animate:false}),{head:0,hand:0,breath:1});
 });
