// THE SENTENCE IS PRINTED ONCE.
//
// The register printed every correspondence row's sentence twice — once as the row's
// headline, once as the grey line under it — on ten consecutive rows, and the mail window
// printed it a third time as the letter's body. The rule that closed it is a comparison,
// not a rewording: when the detail is already the end of (or the whole of) the headline,
// the second copy is not drawn. Nothing about that rule is visible to any other test, so
// a later pass could join the two strings again and every suite would still pass.
//
// These tests hold the rule at all three places it is applied: the helper itself, the
// register's own row, and the letter in the mail window.
import test from 'node:test';
import assert from 'node:assert/strict';
import { describeEvent, withoutEcho } from '../src/ledger.js';
import { renderThread } from '../src/mail_thread.js';
import { escapeHtml } from '../src/html.js';

const options = { escape: escapeHtml, timezone: 'UTC' };

test('a detail that repeats the whole headline is not handed back', () => {
  assert.equal(withoutEcho('Niciun material aprobat.', 'Niciun material aprobat.'), '');
});

test('a detail that is the end of the headline is not handed back', () => {
  assert.equal(
    withoutEcho('publish: COMPLETED — Niciun material aprobat.', 'Niciun material aprobat.'),
    '',
  );
});

test('case and the space around a sentence do not make it a different sentence', () => {
  assert.equal(withoutEcho('publish: COMPLETED — NICIUN MATERIAL.', '  niciun material.  '), '');
});

test('a detail that says something the headline does not is kept, whole', () => {
  assert.equal(
    withoutEcho('publish: COMPLETED — Niciun material aprobat.', 'Two renders failed.'),
    'Two renders failed.',
  );
});

test('a headline that merely starts with the detail is not an echo', () => {
  assert.equal(withoutEcho('Niciun material aprobat de QC.', 'Niciun material'), 'Niciun material');
});

test('nothing to compare against leaves the detail alone, and no detail stays nothing', () => {
  assert.equal(withoutEcho('', 'Niciun material.'), 'Niciun material.');
  assert.equal(withoutEcho('publish: COMPLETED', ''), '');
  assert.equal(withoutEcho(null, undefined), '');
});

test('a register row whose excerpt repeats its subject says the sentence once', () => {
  const item = describeEvent(
    {
      event_type: 'agent.message_posted',
      aggregate_id: 'm-9',
      payload: {
        intent: 'STATUS',
        subject: 'publish: COMPLETED — Niciun material aprobat de QC.',
        excerpt: 'Niciun material aprobat de QC.',
        from_name: 'Vera (Publisher)',
      },
    },
    {},
  );
  assert.equal(item.text, 'publish: COMPLETED — Niciun material aprobat de QC.');
  assert.equal(item.excerpt, '');
  assert.equal(item.text.indexOf('Niciun material'), item.text.lastIndexOf('Niciun material'));
});

test('a register row whose excerpt adds something still carries both', () => {
  const item = describeEvent(
    {
      event_type: 'agent.message_posted',
      aggregate_id: 'm-10',
      payload: {
        intent: 'STATUS',
        subject: 'render: FAILED',
        excerpt: 'Two of five renders failed.',
        from_name: 'Kael (Video Editor)',
      },
    },
    {},
  );
  assert.equal(item.excerpt, 'Two of five renders failed.');
  assert.ok(item.text.includes('render: FAILED'));
  assert.ok(item.text.includes('Two of five renders failed.'));
});

test('a letter whose body repeats its own subject prints the body once', () => {
  const html = renderThread(
    {
      thread_id: 't-9',
      subject: 'publish: COMPLETED — Niciun material aprobat de QC.',
      messages: [
        {
          id: 'm-9',
          intent: 'STATUS',
          from_name: 'Vera (Publisher)',
          to_name: 'Sarah (Director)',
          subject: 'publish: COMPLETED — Niciun material aprobat de QC.',
          body_text: 'Niciun material aprobat de QC.',
          created_at: '2026-09-12T10:37:00+00:00',
          status: 'OPEN',
        },
      ],
    },
    options,
  );
  assert.equal(html.indexOf('Niciun material'), html.lastIndexOf('Niciun material'));
});

test('a letter whose body says more than its subject still prints the body', () => {
  const html = renderThread(
    {
      thread_id: 't-10',
      subject: 'render: FAILED',
      messages: [
        {
          id: 'm-10',
          intent: 'STATUS',
          from_name: 'Kael (Video Editor)',
          to_name: 'Sarah (Director)',
          subject: 'render: FAILED',
          body_text: 'Two of five renders failed.',
          created_at: '2026-09-12T10:37:00+00:00',
          status: 'OPEN',
        },
      ],
    },
    options,
  );
  assert.ok(html.includes('Two of five renders failed.'));
});

test('a letter whose subject is the window title prints that sentence once, and keeps its tag', () => {
  // Measured 2026-09-23: the window's title is the thread's subject, so a one-letter
  // thread printed the same sentence twice, 150px apart.
  const subject = 'publish: COMPLETED — Niciun material aprobat de QC.';
  const html = renderThread(
    {
      thread_id: 't-11',
      subject,
      messages: [
        {
          id: 'm-11',
          intent: 'STATUS',
          from_name: 'Vera (Publisher)',
          to_name: 'Sarah (Director)',
          subject,
          body_text: subject,
          created_at: '2026-09-12T10:37:00+00:00',
          status: 'OPEN',
        },
      ],
    },
    options,
  );
  assert.equal(html.split('Niciun material aprobat de QC.').length - 1, 0);
  assert.ok(html.includes('policy-tag'));
});

test('a letter whose subject differs from the window title still prints its own subject', () => {
  const html = renderThread(
    {
      thread_id: 't-12',
      subject: 'The thread about the render',
      messages: [
        {
          id: 'm-12',
          intent: 'STATUS',
          from_name: 'Kael (Video Editor)',
          to_name: 'Sarah (Director)',
          subject: 'edit_and_qc: COMPLETED — Niciun material nou de verificat.',
          body_text: 'Niciun material nou de verificat.',
          created_at: '2026-09-12T10:37:00+00:00',
          status: 'OPEN',
        },
      ],
    },
    options,
  );
  assert.ok(html.includes('edit_and_qc: COMPLETED'));
});
