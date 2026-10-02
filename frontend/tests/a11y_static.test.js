// PAGE_SETTINGS_ERRORS (PAGE-19): ten controls of the page were named only by their placeholder,
// which a screen reader may not read and which disappears as he types; the shooting sheet's
// repaint dropped keyboard focus to <body> after every press; and its role=status notice was a new
// node each time, which assistive technology may not announce.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');

/** Every input, select and textarea of the page that a person fills or chooses. */
function controls(html) {
  const found = [];
  const pattern = /<(input|select|textarea)\b([^>]*)>/g;
  let match;
  while ((match = pattern.exec(html))) {
    const attrs = match[2];
    const type = (/\btype="([^"]*)"/.exec(attrs) || [])[1] || '';
    if (['hidden', 'submit', 'button', 'reset'].includes(type)) continue;
    found.push({ at: match.index, tag: match[1], attrs, id: (/\bid="([^"]*)"/.exec(attrs) || [])[1] || '' });
  }
  return found;
}

/** A control is named by aria-label, aria-labelledby, a <label for>, or a <label> around it. */
function named(html, control) {
  if (/\baria-label(ledby)?="[^"]+"/.test(control.attrs)) return true;
  if (control.id && new RegExp(`<label\\b[^>]*\\bfor="${control.id}"`).test(html)) return true;
  const before = html.slice(0, control.at);
  return before.lastIndexOf('<label') > before.lastIndexOf('</label>');
}

test('no control of the page is named only by its placeholder', () => {
  const unnamed = controls(HTML)
    .filter((c) => !named(HTML, c))
    .map((c) => `${c.tag}#${c.id || '?'}${/placeholder=/.test(c.attrs) ? ' (placeholder only)' : ''}`);
  assert.deepEqual(unnamed, []);
});

test('the ten controls the audit named have a name of their own', () => {
  for (const id of ['agent-run-objective', 'allowed-host-input', 'source-url', 'budget-limit', 'funding-amount',
    'funding-note', 'funding-fx-rate', 'funding-fx-source', 'funding-rate', 'mail-reply-text']) {
    const control = controls(HTML).find((c) => c.id === id);
    assert.ok(control, id);
    assert.ok(named(HTML, control), id);
  }
});

test('the sheet\'s notice lives outside [data-sheet-body] and is one persistent element', () => {
  const drawer = MAIN.slice(MAIN.indexOf('function sheetDialog()'), MAIN.indexOf('function sheetDialog()') + 2500);
  const status = drawer.indexOf('data-sheet-status');
  const body = drawer.indexOf('data-sheet-body');
  assert.ok(status > 0, 'the drawer has its own status line');
  assert.ok(status < body, 'the status line is not inside the body a repaint replaces');
  assert.match(drawer, /role="status"[^>]*data-sheet-status|data-sheet-status[^>]*role="status"/);
  // the repaint writes the notice into that element and passes none into the body
  const paint = MAIN.slice(MAIN.indexOf('function paintSheet()'), MAIN.indexOf('async function loadSheet()'));
  assert.match(paint, /notice: ''/);
  assert.match(paint, /sheetStatus\(/);
});

test('a repaint gives keyboard focus back to the key that had it', () => {
  const paint = MAIN.slice(MAIN.indexOf('function paintSheet()'), MAIN.indexOf('async function loadSheet()'));
  assert.match(paint, /focusKey\(/);
  assert.match(paint, /restoreFocus\(/);
});
