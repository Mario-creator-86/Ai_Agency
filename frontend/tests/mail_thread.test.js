import test from 'node:test';
import assert from 'node:assert/strict';
import { renderThread } from '../src/mail_thread.js';
import { escapeHtml } from '../src/html.js';

const options = { escape: escapeHtml, timezone: 'UTC' };

test('a thread renders as letters, oldest first, with both ends, the date and the text', () => {
  const html = renderThread(
    {
      thread_id: 't-1',
      subject: 'Sursa cifrei',
      messages: [
        { id: 'm-1', intent: 'REQUEST_INFO', from_name: 'Sarah (Director)', to_name: 'Elena (Fact Checker)', subject: 'Sursa cifrei', body_text: 'Elena, pe ce stă 40%?\nSarah', created_at: '2026-09-12T08:15:00+00:00', status: 'ANSWERED', resolved_by: 'Elena (Fact Checker)', resolution: 'Raportul IEA.' },
        { id: 'm-2', intent: 'STATUS', from_name: 'Elena (Fact Checker)', to_name: 'Sarah (Director)', subject: 'Re: Sursa cifrei', body_text: 'Raportul IEA.', created_at: '2026-09-12T08:20:00+00:00', status: 'OPEN' },
      ],
    },
    options,
  );
  assert.ok(html.indexOf('data-message="m-1"') < html.indexOf('data-message="m-2"'));
  assert.ok(html.includes('<strong>Sarah (Director)</strong> <span class="mail-arrow">→</span> <strong>Elena (Fact Checker)</strong>'));
  assert.ok(html.includes('Întrebare'));
  assert.ok(html.includes('Elena, pe ce stă 40%?\nSarah'));
  assert.ok(html.includes('răspuns de Elena (Fact Checker) — Raportul IEA.'));
  assert.ok(html.includes('2026'));
});

test('a message from before letters existed shows what its body can say, never raw JSON', () => {
  const html = renderThread(
    { thread_id: 't-2', subject: 'publish', messages: [{ id: 'm-3', intent: 'STATUS', subject: 'publish: SKIPPED', body_json: { stage: 'publish', reason: 'Niciun canal legat.' }, created_at: '2026-09-11T20:00:00+00:00', status: 'OPEN' }] },
    options,
  );
  assert.ok(html.includes('Niciun canal legat.'));
  assert.ok(!html.includes('{'));
});

test('text written by a model is escaped before it reaches the window', () => {
  const html = renderThread(
    { thread_id: 't-3', subject: 'x', messages: [{ id: 'm-4', intent: 'STATUS', subject: '<img src=x onerror=1>', body_text: '<b>bold</b>', created_at: '', status: 'OPEN' }] },
    options,
  );
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;b&gt;bold&lt;/b&gt;'));
});

test('an empty thread says so', () => {
  assert.ok(renderThread({ thread_id: 't', subject: '', messages: [] }, options).includes('Firul este gol'));
});

test('a letter to the Owner is marked as waiting for the Owner while it is open', () => {
  const html = renderThread(
    { thread_id: 't-4', subject: 'x', messages: [{ id: 'm-5', intent: 'ESCALATE', from_name: 'Sarah (Director)', to_name: 'Owner', for_owner: true, subject: 'Am nevoie de decizia ta', body_text: 'Titlul.', created_at: '', status: 'OPEN' }] },
    options,
  );
  assert.ok(html.includes('is-owner'));
  assert.ok(html.includes('așteaptă răspunsul tău'));
});
