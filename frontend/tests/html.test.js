import test from 'node:test';
import assert from 'node:assert/strict';
import { escapeHtml } from '../src/html.js';

test('every character that changes the meaning of markup is neutralised', () => {
  assert.equal(escapeHtml('<script>'), '&lt;script&gt;');
  assert.equal(escapeHtml('a & b'), 'a &amp; b');
  assert.equal(escapeHtml('say "hi"'), 'say &quot;hi&quot;');
  assert.equal(escapeHtml("it's"), 'it&#39;s');
});

test('an injected image handler cannot survive as markup', () => {
  // The shape an untrusted title would take: a language model or a research source can put
  // anything in a string that the interface later interpolates into HTML.
  const hostile = '<img src=x onerror="alert(1)">';
  const escaped = escapeHtml(hostile);
  assert.ok(!escaped.includes('<img'));
  assert.ok(!escaped.includes('onerror="'));
  assert.equal(escaped, '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
});

test('a value cannot break out of a quoted attribute', () => {
  const breakout = '" autofocus onfocus="alert(1)';
  assert.ok(!escapeHtml(breakout).includes('"'));
});

test('the ampersand is escaped first, so entities are not double-decoded', () => {
  // Escaping < before & would turn "&lt;" into "&amp;lt;" only if & were handled afterwards;
  // a single pass over the original string is what keeps this correct.
  assert.equal(escapeHtml('&lt;'), '&amp;lt;');
});

test('missing values read as missing rather than as the words null or undefined', () => {
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(undefined), '');
  assert.equal(escapeHtml(0), '0');
  assert.equal(escapeHtml(false), 'false');
});
