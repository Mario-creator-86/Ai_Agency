// A letter the studio's sweep closed with nobody's answer is stored ANSWERED (the sheet repair
// may still resolve it) and carries `expired`; the page shows it as closed unanswered, never as
// «răspuns» (the audit of 2026-10-16, STUB-006).
import test from 'node:test';
import assert from 'node:assert/strict';
import { renderThread } from '../src/mail_thread.js';
import { letterStateWord } from '../src/dialog_words.js';
import { escapeHtml } from '../src/html.js';

const expiredLetter = {
  id: 'm-1',
  intent: 'REQUEST_INFO',
  from_name: 'Sarah (Director)',
  to_name: 'Marcus (Script Writer)',
  subject: 'Ce cârlig merge',
  body_text: 'Marcus, ce cârlig merge?',
  created_at: '2026-10-12T08:15:00+00:00',
  status: 'ANSWERED',
  expired: true,
  resolved_by: 'Studioul (cereri expirate)',
  resolution: 'Închisă de studio fără răspuns: destinatarul nu a reușit să răspundă.',
};

test('a letter the studio closed unanswered is never shown as answered', () => {
  const html = renderThread({ thread_id: 'm-1', subject: 'Ce cârlig merge', messages: [expiredLetter] }, { escape: escapeHtml });
  assert.ok(html.includes('închis fără răspuns de Studioul (cereri expirate)'), html);
  assert.ok(!html.includes('<div class="mail-footer">răspuns'), html);
});

test('a letter an employee answered still reads «răspuns»', () => {
  const answered = { ...expiredLetter, expired: false, resolved_by: 'Marcus (Script Writer)', resolution: 'Cel cu cifra.' };
  const html = renderThread({ thread_id: 'm-1', subject: 'Ce cârlig merge', messages: [answered] }, { escape: escapeHtml });
  assert.ok(html.includes('răspuns de Marcus (Script Writer) — Cel cu cifra.'), html);
});

test('the chat line names the expired state in words', () => {
  assert.equal(letterStateWord('EXPIRED'), 'închis fără răspuns');
  assert.equal(letterStateWord('ANSWERED'), 'răspuns');
});

// The register and the live window draw the answer's event (`describeEvent`): an ask the sweep
// closed is never «a răspuns la un mesaj» there either (the review of 2026-10-16). The event
// says it by `expired`; an event recorded before the flag existed says it by its closer.
test('the register never says an employee answered an ask the studio closed unanswered', async () => {
  const { describeEvent } = await import('../src/ledger.js');
  const event = (payload) => ({ event_type: 'agent.message_answered', aggregate_id: 'm-1', payload });
  for (const payload of [
    { intent: 'REQUEST_INFO', subject: 'Ce cârlig merge', resolved_by: 'Studioul (cereri expirate)', expired: true },
    { intent: 'REQUEST_INFO', subject: 'Ce cârlig merge', resolved_by: 'Studioul (cereri expirate)' },
  ]) {
    const row = describeEvent(event(payload), {});
    assert.ok(!/răspuns la/.test(row.label), JSON.stringify(row));
    assert.match(row.label, /fără răspuns/);
    assert.equal(row.text, 'Ce cârlig merge');
    assert.equal(row.who, 'Studioul');
  }
  const answered = describeEvent(
    event({ intent: 'REQUEST_INFO', subject: 'Ce cârlig merge', resolved_by: 'Marcus (Script Writer)', expired: false }),
    {},
  );
  assert.equal(answered.label, 'a răspuns la un mesaj');
});
