// W25 «one now at a time»: at 16× the end of the replay showed five room chips at once, «acum:
// raportare…», «acum: publicare», «acum: producție media», «acum: montaj…», «acum: episodul din
// serial», beside a bar that said «rularea s-a încheiat». A run's stages follow one another, so only
// the newest lit room says «acum: …»; the older ones keep their fading light, without words.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { chipStage } from '../src/hq_arrivals.js';

const WORLD = fs.readFileSync(new URL('../src/hq_world.js', import.meta.url), 'utf8');

test('the chip belongs to the newest lit room only', () => {
  const flares = [
    { zone: 'a', stage: 'publish', strength: 0.4, age: 2600 },
    { zone: 'b', stage: 'report', strength: 1, age: 300 },
    { zone: 'c', stage: 'media', strength: 0.2, age: 3000 },
  ];
  assert.equal(chipStage(flares), 'report');
});

test('no lit room, no chip', () => {
  assert.equal(chipStage([]), null);
  assert.equal(chipStage(null), null);
});

test('rooms of the same stage share the chip (one chip is drawn for it)', () => {
  assert.equal(chipStage([{ zone: 'a', stage: 'media', strength: 1, age: 100 }, { zone: 'b', stage: 'media', strength: 1, age: 100 }]), 'media');
});

test('the renderer labels only the chip stage', () => {
  const rims = WORLD.slice(WORLD.indexOf("  drawRoomRims(ctx, state, part = 'all', over = null) {"), WORLD.indexOf('  drawArrivals(ctx, state) {'));
  assert.match(rims, /const now = chipStage\(flares\);/);
  assert.match(rims, /f\.stage !== now/);
});
