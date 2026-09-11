import test from 'node:test';
import assert from 'node:assert/strict';
import {
  bubblePages,
  bubbleFrame,
  bubbleDurationMs,
  CHARS_PER_SECOND,
  HOLD_SECONDS,
  LINE_CHARS,
  MAX_PAGES,
  PAGE_LINES,
} from '../src/speech_bubble.js';

test('a long answer is wrapped into pages of three short lines and nothing is dropped', () => {
  const text = 'I am Dr. Aris, the Lead Researcher at AMN-AI, an autonomous AI media studio. ' +
    'Today I read four pages and extracted nine claims for verification.';
  const pages = bubblePages(text);
  assert.ok(pages.length > 1, 'more than one page');
  for (const page of pages) {
    assert.ok(page.length <= PAGE_LINES);
    for (const line of page) assert.ok(line.length <= LINE_CHARS, line);
  }
  const rebuilt = pages.flat().join(' ').replace(/\s+/g, ' ');
  assert.equal(rebuilt, text.toUpperCase().replace(/\s+/g, ' '));
});

test('a word longer than a line is split, not lost', () => {
  const pages = bubblePages('see https://www.iana.org/help/example-domains now');
  const joined = pages.flat().join('');
  assert.ok(joined.includes('HTTPS://WWW.IANA.ORG/HE'));
  assert.ok(joined.includes('LP/EXAMPLE-DOMAINS'));
});

test('the frame types a page out, holds it, then moves to the next page', () => {
  const pages = bubblePages('one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen');
  assert.ok(pages.length >= 2);
  const start = bubbleFrame(pages, 0);
  assert.equal(start.pageIndex, 0);
  assert.equal(start.lines.join(''), '');
  const firstChars = pages[0].join(' ').length;
  const typed = bubbleFrame(pages, firstChars / CHARS_PER_SECOND);
  assert.deepEqual(typed.lines, pages[0], 'the whole first page is visible once typed');
  assert.equal(typed.done, false);
  const next = bubbleFrame(pages, firstChars / CHARS_PER_SECOND + HOLD_SECONDS + 0.01);
  assert.equal(next.pageIndex, 1, 'after the hold the second page starts');
  assert.equal(next.pageCount, pages.length);
  const end = bubbleFrame(pages, 1e6);
  assert.equal(end.pageIndex, pages.length - 1);
  assert.deepEqual(end.lines, pages[pages.length - 1]);
  assert.equal(end.done, true);
});

test('the bubble stays up exactly as long as reading the whole answer takes', () => {
  const pages = bubblePages('short');
  assert.equal(bubbleDurationMs(pages), 4000, 'a short bubble still holds a readable minimum');
  const long = bubblePages('word '.repeat(120));
  const expected = long.reduce((t, p) => t + p.join(' ').length / CHARS_PER_SECOND + HOLD_SECONDS, 0);
  assert.equal(bubbleDurationMs(long), Math.round(expected * 1000));
  assert.ok(long.length <= MAX_PAGES);
});
