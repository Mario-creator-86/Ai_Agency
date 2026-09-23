// THE EIGHT DOORS OPEN ONTO ONE ROOM, AND A METER MEANS WHAT IT DRAWS.
//
// Two rules of this pass live only in the stylesheet, where nothing can see them break.
//
// ONE TOP EDGE. The dialogs used to be vertically centred, so the close button moved
// halfway down the screen depending on which door was opened (measured at 1920: seven at
// y55-73, Story y118, Settings y283, Mail y300). They are pinned to one offset now, and
// Settings gave up its own narrower cap for the family width. A later pass re-centring one
// dialog, or giving one its own width again, would put the family back the way it was and
// no test would notice.
//
// ONE TRACK. The module meter's column was `auto`, so the longest status word pulled its
// own row's meter left: NEIMPLEMENTAT drew a longer grey bar starting 18px further left
// than PARTIAL's fill, and the unbuilt modules read as further along than the half-built
// ones. The column is a fixed token now, and both the wide rule and the narrow one must
// use it or the two halves of the list disagree again.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

/** Every declaration of one property, in source order. */
function declarations(name) {
  return [...STYLE.matchAll(new RegExp(`--${name}:\s*([^;]+);`, 'g'))].map((m) => m[1].trim());
}

test('the top edge every dialog opens at is a token, declared once in the token block', () => {
  const declared = declarations('dialog-top');
  assert.equal(declared.length, 1, '--dialog-top is declared exactly once');
  assert.ok(/^\d+(\.\d+)?(vh|px|rem)$/.test(declared[0]), `--dialog-top is a length: ${declared[0]}`);
});

test('the dialog shell is pinned to that edge rather than centred', () => {
  assert.ok(
    /\.studio-dialog\[open\][^{]*\{[^}]*margin-block:\s*var\(--dialog-top\)\s+auto/s.test(STYLE),
    '.studio-dialog[open] takes its top margin from --dialog-top and lets the bottom run',
  );
});

test('the one dialog allowed to stay centred is the expanded inspector, and it says so', () => {
  assert.ok(
    /\.studio-dialog\[open\]\.dialog-max\s*\{\s*margin-block:\s*auto/.test(STYLE),
    'only .dialog-max opts back out of the shared top edge',
  );
});

test('Settings no longer carries a width of its own: it takes the family width', () => {
  const rule = /\.settings-dialog,\s*\.settings-dialog\[open\]\s*\{([^}]*)\}/.exec(STYLE);
  assert.ok(rule, 'the Settings width rule is still there to be read');
  assert.ok(rule[1].includes('var(--dialog-w)'), 'Settings sizes itself from --dialog-w');
  assert.ok(
    !/\b\d+px\b/.test(rule[1].replace(/var\([^)]*\)/g, '')),
    `Settings states no width literal of its own: ${rule[1].trim()}`,
  );
});

test('the family width is a token, and the wide screen buys content rather than margin', () => {
  const declared = declarations('dialog-w');
  assert.equal(declared.length, 2, '--dialog-w is stated once for the page and once wider');
  const [base, wide] = declared.map((v) => Number.parseInt(v, 10));
  assert.ok(wide > base, `the wide step is wider than the base: ${wide} > ${base}`);
  assert.ok(
    /@media\s*\(min-width:\s*\d+px\)\s*\{\s*:root\s*\{\s*--dialog-w:/.test(STYLE),
    'the wider value is given at a min-width, not to every screen',
  );
});

test('the module meter column is one fixed width, so all three states draw one track', () => {
  const declared = declarations('module-state-w');
  assert.equal(declared.length, 1, '--module-state-w is declared exactly once');
  // Every row rule the Owner's four widths can reach. The one rule inside
  // @media (max-width: 600px) is deliberately left out: it still lays the row out with an
  // `auto` status column and a meter with no minimum, which is the very geometry that read
  // backwards — a phone has never been one of his widths, and this test says so out loud
  // rather than pretending the narrow rule was fixed too.
  // Where each phone block starts and ends, by matching its braces.
  const phoneBlocks = [];
  for (const opener of STYLE.matchAll(/@media \(max-width: 600px\)\s*\{/g)) {
    let depth = 1;
    let at = opener.index + opener[0].length;
    while (depth > 0 && at < STYLE.length) {
      if (STYLE[at] === '{') depth += 1;
      else if (STYLE[at] === '}') depth -= 1;
      at += 1;
    }
    phoneBlocks.push([opener.index, at]);
  }
  assert.ok(phoneBlocks.length > 0, 'the phone block is still there, and still the exception');
  const onAPhone = (at) => phoneBlocks.some(([from, to]) => at >= from && at < to);
  const rows = [...STYLE.matchAll(/\.modules li[^{]*\{[^}]*grid-template-columns:\s*([^;]+);/g)]
    .filter((m) => !onAPhone(m.index));
  assert.ok(rows.length >= 2, 'the wide rule and the narrow-desktop rule both lay the row out');
  for (const row of rows) {
    assert.ok(
      row[1].includes('var(--module-state-w)'),
      `every .modules row above 600px ends in the same status column, not auto: ${row[1].trim()}`,
    );
  }
});
