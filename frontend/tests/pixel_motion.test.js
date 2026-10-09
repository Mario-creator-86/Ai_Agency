import test from 'node:test';
import assert from 'node:assert/strict';
import { bindSceneMotion } from '../src/pixel_motion.js';

function control(saved, fail = false) {
  let click, changes = 0;
  const attributes = {}, classes = new Set(), label = {};
  const button = {
    setAttribute: (key, value) => { attributes[key] = value; },
    classList: { toggle: (key, value) => value ? classes.add(key) : classes.delete(key) },
    querySelector: () => label,
    addEventListener: (_event, handler) => { click = handler; },
  };
  const storage = () => {
    if (fail) throw new Error('Storage refused');
    return { getItem: () => saved, setItem: (_key, value) => { saved = value; } };
  };
  const motion = bindSceneMotion(button, () => { changes++; }, storage);
  return { motion, attributes, classes, label, click: () => click(), saved: () => saved, changes: () => changes };
}

test('explicit Owner scene default animates and a saved pause survives a new visit', () => {
  for (const saved of [null, 'garbage', 'false']) assert.equal(control(saved).motion.enabled(), true);
  const first = control(null);
  assert.equal(first.attributes['aria-pressed'], 'true');
  assert.equal(first.label.textContent, 'PORNITE');
  first.click();
  assert.equal(first.motion.enabled(), false);
  assert.equal(first.saved(), 'off');
  assert.equal(first.attributes['aria-pressed'], 'false');
  assert.equal(first.classes.has('is-on'), false);
  const returned = control(first.saved());
  assert.equal(returned.motion.enabled(), false);
  returned.click();
  assert.equal(control(returned.saved()).motion.enabled(), true);
  assert.equal(returned.changes(), 1);
});

test('refused storage never prevents the scene from pausing or resuming in this visit', () => {
  const c = control(null, true);
  assert.equal(c.motion.enabled(), true);
  c.click(); assert.equal(c.motion.enabled(), false);
  c.click(); assert.equal(c.motion.enabled(), true);
  assert.equal(c.changes(), 2);
});
