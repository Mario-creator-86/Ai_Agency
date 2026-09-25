// W27, the release judge: the Distribution door listed the five gates a publication must pass,
// each with a green ✓ written into the page. Nothing had been checked: the list says which gates
// the studio enforces, not a result, and a stranger reads a green tick as «passed». The Owner's
// first rule: a mark that looks like a state must come from a real state. The gates stay a
// numbered list of rules; the tag beside the title («PARȚIAL») and the note under it say the rest.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('the publication gates are rules, with no result mark the page wrote itself', () => {
  const list = HTML.match(/<ul class="pub-gate-list">([\s\S]*?)<\/ul>/);
  assert.ok(list, 'the gates list exists');
  assert.equal((list[1].match(/<li>/g) || []).length, 5, 'five gates');
  assert.ok(!/✓|✔|gate-icon/.test(list[1]), 'no tick beside a gate nobody checked');
});
