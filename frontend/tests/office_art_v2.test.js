import test from 'node:test';
import assert from 'node:assert/strict';
import { ramp, mix, withAlpha, DEPARTMENTS, department, AMBIENT, SKIN, HAIR, CLOTH, MAT } from '../src/office_palette.js';
import { PixelGrid } from '../src/pixel_sprites.js';
import { agentLook, modeForAgent, characterMetrics, CHARACTER_BODY_ROWS, HAIR_STYLES, CHARACTER_SPRITE_W } from '../src/office_characters.js';

test('ramps are five tones ordered dark to light and hue-shifted towards the ambient ends', () => {
  const r = ramp('#8a6a3a');
  assert.equal(r.length, 5);
  const lum = (hex) => parseInt(hex.slice(1, 3), 16) + parseInt(hex.slice(3, 5), 16) + parseInt(hex.slice(5, 7), 16);
  for (let i = 1; i < 5; i += 1) assert.ok(lum(r[i]) > lum(r[i - 1]), `tone ${i} lighter than ${i - 1}`);
  assert.equal(r[2], '#8a6a3a', 'the base tone is preserved');
  assert.equal(r[0], mix('#8a6a3a', AMBIENT.shadow, 0.62));
  assert.equal(withAlpha('#ffffff', 0.5), '#ffffff80');
});

test('every department carries a complete material story and unknown types fall back', () => {
  for (const [key, dept] of Object.entries(DEPARTMENTS)) {
    assert.equal(dept.wall.length, 5, `${key} wall ramp`);
    assert.equal(dept.floor.length, 5, `${key} floor ramp`);
    assert.match(dept.accent, /^#[0-9a-f]{6}$/i, `${key} accent`);
    assert.ok(dept.name.length > 0);
  }
  assert.equal(department('NOPE'), DEPARTMENTS.DEFAULT);
  for (const ramps of [SKIN, HAIR]) for (const r of ramps) assert.equal(r.length, 5);
  for (const r of Object.values(CLOTH)) assert.equal(r.length, 5);
  for (const r of Object.values(MAT)) assert.equal(r.length, 5);
});

test('pixel grid blits letters, outlines the silhouette and never paints outside its bounds', () => {
  const g = new PixelGrid(6, 6);
  g.blit(['.AA.', '.AA.'], { A: '#ff0000' }, 1, 1);
  assert.equal(g.at(2, 1), '#ff0000');
  assert.equal(g.at(1, 1), null);
  g.outline('#000000');
  assert.equal(g.at(1, 1), '#000000', 'outline hugs the left edge');
  assert.equal(g.at(2, 0), '#000000', 'outline hugs the top edge');
  assert.equal(g.at(4, 1), '#000000', 'outline hugs the right edge');
  assert.equal(g.at(0, 0), null, 'diagonal corners stay clear');
  assert.equal(g.at(5, 5), null);
  g.plot(-1, 2, '#00ff00');
  g.plot(9, 9, '#00ff00');
  assert.ok(g.data.every((c) => c !== '#00ff00'), 'out-of-bounds plots are ignored');
});

test('character templates are rectangular, and every hair style fits the sprite width', () => {
  const w = CHARACTER_SPRITE_W;
  for (const row of CHARACTER_BODY_ROWS) assert.equal(row.length, w, `body row "${row}"`);
  for (const [name, style] of Object.entries(HAIR_STYLES)) {
    for (const row of style.rows) assert.equal(row.length, w, `${name} row "${row}"`);
  }
});

test('an agent always looks the same; costume follows the role; posture follows backend state only', () => {
  const a = agentLook('agent-1', 'Researcher');
  const b = agentLook('agent-1', 'Researcher');
  assert.deepEqual(a, b);
  assert.notDeepEqual(agentLook('agent-2', 'Researcher').skin.concat(agentLook('agent-2', 'Researcher').hair), a.skin.concat(a.hair).concat(['x']));
  assert.equal(agentLook('any', 'VoiceArtist').headset, true, 'voice artists wear a headset');
  assert.equal(agentLook('x', 'Director').garment, CLOTH.navy, 'the director wears the navy blazer');
  assert.equal(modeForAgent({ runtime_state: 'WORKING', lifecycle: 'ACTIVE' }), 'work');
  assert.equal(modeForAgent({ runtime_state: 'WORKING', lifecycle: 'PAUSED' }), 'sleep', 'a paused agent never types');
  assert.equal(modeForAgent({ runtime_state: 'THINKING' }), 'think');
  assert.equal(modeForAgent({ runtime_state: 'WHATEVER' }), 'idle');
  const m = characterMetrics(100);
  assert.ok(m.headTop < m.headBottom && m.headBottom < m.shoulders && m.shoulders < m.waist);
  assert.ok(m.waist <= 100, 'the waist sits at or behind the desk plane so the desk hides it');
});
