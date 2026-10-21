import test from 'node:test';
import assert from 'node:assert/strict';
import { PIXEL_LAYOUT } from '../src/pixel_desks.js';
import { outdoorsAt } from '../src/pixel_environment.js';
import { windowFoliagePixel } from '../src/pixel_windows.js';

test('window view crops use real exterior artwork at the same world height',()=>{
  assert.equal(PIXEL_LAYOUT.outdoors.windows.length,5);
  for(const pane of PIXEL_LAYOUT.outdoors.windows){
    const s=pane.source;
    assert.equal(s.y,pane.y,'lower floors see lower city, not another sunset');
    for(const x of [s.x,s.x+s.width-1])for(const y of [s.y,s.y+s.height-1])assert.ok(outdoorsAt(x,y));
    assert.ok(s.x>=0&&s.x+s.width<=PIXEL_LAYOUT.world.width);
    assert.ok(pane.x>=0&&pane.x+pane.width<=PIXEL_LAYOUT.world.width);
  }
});

test('foliage occlusion never treats old city silhouettes or sunset highlights as frame',()=>{
  assert.equal(windowFoliagePixel(240,145,110),false);
  assert.equal(windowFoliagePixel(124,93,158),false);
  assert.equal(windowFoliagePixel(50,90,120),false);
  assert.equal(windowFoliagePixel(48,93,37),true);
  for(const pane of PIXEL_LAYOUT.outdoors.windows)assert.ok(pane.frame_bars.length>=2);
});
