import test from 'node:test';
import assert from 'node:assert/strict';
import { renderThread } from '../src/mail_thread.js';
import { escapeHtml } from '../src/html.js';

const options = { escape: escapeHtml, timezone: 'UTC' };

test('a thread renders as letters, newest first, with both ends, the date and the text', () => {
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
  assert.ok(html.indexOf('data-message="m-2"') < html.indexOf('data-message="m-1"'));
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

// PAGE_OWNER_DAY (PAGE-02): a sheet letter is a key to the film's sheet, never a raw API path.
test('a sheet letter shows «Deschide foaia de filmare» and never prints the /api/v1 path', () => {
  const id = '3ec1740c-0000-4000-8000-000000000001';
  const html = renderThread(
    {
      thread_id: 't-5',
      subject: 'Filmul «Nepal» așteaptă răspunsul tău',
      messages: [{
        id: 'm-6',
        intent: 'ESCALATE',
        from_name: 'Sarah (Director)',
        to_name: 'Owner',
        for_owner: true,
        subject: 'Filmul «Nepal» așteaptă răspunsul tău',
        body_json: { kind: 'owner_shooting_sheet', storyboard_id: id, sheet_url: `/api/v1/media/storyboards/${id}/shooting-sheet`, approval_id: 'a-1' },
        body_text: `Imaginile: 18 credite.\nFoaia de filmare: /api/v1/media/storyboards/${id}/shooting-sheet`,
        created_at: '',
        status: 'OPEN',
      }],
    },
    options,
  );
  assert.ok(html.includes(`data-sheet-open="${id}"`));
  assert.ok(html.includes('Deschide foaia de filmare'));
  assert.ok(!html.includes('/api/v1'), 'the raw path is never printed');
  assert.ok(html.includes('Imaginile: 18 credite.'), 'the rest of the letter stays');
});

test('a letter that names no film has no sheet key', () => {
  const html = renderThread(
    { thread_id: 't-6', subject: 'x', messages: [{ id: 'm-7', intent: 'STATUS', subject: 'QC', body_json: { kind: 'owner_qc_failed', reason: 'x' }, body_text: 'QC a picat.', created_at: '', status: 'OPEN' }] },
    options,
  );
  assert.ok(!html.includes('data-sheet-open'));
});

test('a report the studio wrote by itself is not shown as written by the Owner', () => {
  // 2026-10-03: the worker's "Blocaje foaie" report (no agent sender) read "Proprietar →
  // Sarah (Director)" in the Owner's own correspondence, as if he had written it.
  const html = renderThread(
    {
      thread_id: 't',
      subject: 'Blocaje foaie',
      messages: [
        { id: 'a', intent: 'REQUEST_REVIEW', subject: 'Blocaje foaie', body_text: 'Foaia este blocată.', body_json: { executed_by_worker: true }, from_name: null, to_name: 'Sarah (Director)', created_at: '2026-10-03T17:36:00Z' },
        { id: 'b', intent: 'REQUEST_INFO', subject: 'Întrebare', body_text: 'Cât costă?', body_json: { from: 'Owner' }, from_name: null, to_name: 'Sarah (Director)', created_at: '2026-10-03T17:37:00Z' },
      ],
    },
    options,
  );
  assert.ok(html.includes('Studioul (verificare automată)'), html);
  assert.equal((html.match(/Proprietar/g) || []).length, 1, "only the Owner's own letter is his");
});


test('an Owner status report does not ask for an answer', () => {
  const html = renderThread({ thread_id: 'notice', subject: 'Refacerea continuă', messages: [
    { id: 'n', intent: 'STATUS', to_name: 'Owner', for_owner: true, status: 'OPEN', body_json: { outcome: 'BOUGHT_WAITING' }, body_text: 'Studioul verifică refacerea.' }
  ] }, options);
  assert.ok(!html.includes('așteaptă răspunsul tău'));
  assert.ok(!html.includes('is-owner'));
});

test('an actual paid approval still asks the Owner even in a status envelope', () => {
  const html = renderThread({ thread_id: 'approval', subject: 'Aprobă', messages: [
    { id: 'a', intent: 'STATUS', to_name: 'Owner', for_owner: true, status: 'OPEN', body_json: { outcome: 'ASKED', approval_id: 'paid-1' } }
  ] }, options);
  assert.ok(html.includes('așteaptă răspunsul tău'));
});
