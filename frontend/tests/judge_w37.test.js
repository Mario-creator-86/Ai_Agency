// W37, THE RELEASE JUDGE OF W36. Filmed with a stand-in stream frame, the cold entry no longer
// double-exposed the plates and the stream, but the render's panel showed its own ground for ~60 ms
// between the plates' last frame and the picture's first (ui/w37 entry_1920: plates gone at 735 ms,
// stream visible from 798). The hold now ends at ENTRY.streamMs, where the plates are under 5 %, and
// the picture is full before the push ends. Under reduced motion the decision's glass step was still
// given its animation (the reduced rule was outranked by the later rule of the same specificity).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { ENTRY } from '../src/title_frame.js';

const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const TITLE = fs.readFileSync(new URL('../src/title_screen.js', import.meta.url), 'utf8');

/** y of a CSS cubic-bezier timing function at progress x (the curve's x is time). */
function bezierY(p1x, p1y, p2x, p2y, x) {
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 48; i++) {
    const t = (lo + hi) / 2;
    const cx = 3 * (1 - t) ** 2 * t * p1x + 3 * (1 - t) * t * t * p2x + t ** 3;
    if (cx < x) lo = t; else hi = t;
  }
  const t = (lo + hi) / 2;
  return 3 * (1 - t) ** 2 * t * p1y + 3 * (1 - t) * t * t * p2y + t ** 3;
}

test('a cold push lets the stream\'s picture show once the plates are under 5 %, and it is full before the push ends', () => {
  assert.ok(ENTRY.streamMs < ENTRY.pushMs, 'before the push ends');
  const durFast = Number(/--dur-fast:\s*(\d+)ms/.exec(STYLE)?.[1]);
  assert.ok(durFast > 0, 'the stylesheet names --dur-fast');
  assert.ok(ENTRY.streamMs + durFast <= ENTRY.pushMs + durFast / 2, 'the picture is full within half a fade of the push\'s end');
  assert.ok(ENTRY.streamMs + durFast < ENTRY.totalMs, 'and before the entry ends, when the cold-entry mark and its transition go');
  // the plates' fade: title-push holds opacity 1 to 30 % and fades to 0 at 100 %, along --ease-push
  const ease = /--ease-push:\s*cubic-bezier\(([^)]+)\)/.exec(STYLE)?.[1].split(',').map(Number);
  assert.ok(ease && ease.length === 4, 'the push has its own curve');
  const push = /@keyframes title-push \{([^}]*\}[^}]*\}[^}]*\})/s.exec(STYLE)?.[1] || '';
  assert.match(push, /30%\s*\{\s*opacity:\s*1;/);
  assert.match(push, /100%\s*\{[^}]*opacity:\s*0;/);
  const hold = 0.3 * ENTRY.pushMs;
  const progress = (ENTRY.streamMs - hold) / (ENTRY.pushMs - hold);
  const platesAt = 1 - bezierY(ease[0], ease[1], ease[2], ease[3], progress);
  assert.ok(platesAt < 0.05, `the plates are at ${platesAt.toFixed(3)} when the picture begins`);
  assert.match(TITLE, /classList\.remove\('is-pushing'\)[^\n]*ENTRY\.streamMs\)/);
  // the picture fades in over --dur-fast once the hold ends, on the cold entry only
  assert.match(STYLE, /body\.is-cold-entry:not\(\.is-pushing\)[^{]*\.live-stream-still[^{]*\{[^}]*transition:\s*opacity var\(--dur-fast\)/s);
});

test('under reduced motion the decision\'s glass step has no animation at all', () => {
  const reduced = STYLE.slice(STYLE.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(reduced, /\.decision-plate \.decision-confirm \{ animation: none; \}/, 'named from its plate, so it outranks the later rule');
  const own = /\n\.decision-confirm \{[^}]*\}/s.exec(STYLE)?.[0] || '';
  assert.match(own, /animation: decision-step/);
  assert.ok(STYLE.indexOf('.decision-plate .decision-confirm { animation: none; }') < STYLE.indexOf(own), 'the reduced rule is written earlier and wins by specificity, not by order');
});
