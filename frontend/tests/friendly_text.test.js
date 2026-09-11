import test from 'node:test';
import assert from 'node:assert/strict';
import { extractJson, friendlyAnswer, salvageItems } from '../src/friendly_text.js';

test('the pages a researcher proposes become a titled list of links with reasons', () => {
  const html = friendlyAnswer(
    JSON.stringify({
      urls: [
        { url: 'https://en.wikipedia.org/wiki/Autonomous_robot', why: 'Prezentare completă a sistemelor autonome.' },
        { url: 'https://mars.nasa.gov/mars2020/', why: 'Navigația autonomă a roverului Perseverance.' },
      ],
    }),
  );
  assert.ok(html.includes('Îți propun 2 pagini de citit:'));
  assert.ok(html.includes('href="https://en.wikipedia.org/wiki/Autonomous_robot"'));
  assert.ok(html.includes('Navigația autonomă a roverului Perseverance.'));
  assert.ok(html.includes('Răspunsul exact al modelului'));
});

test('extracted claims are numbered sentences, not a JSON array', () => {
  const html = friendlyAnswer(
    JSON.stringify({
      claims: [
        { claim_text: 'IANA rezervă exemplu.net pentru documentație.', importance: 'CRITICAL', confidence: 0.9 },
        { claim_text: 'Subdomeniile exemplului nu pot fi înregistrate.', importance: 'SUPPORTING' },
      ],
    }),
  );
  assert.ok(html.includes('Am extras 2 afirmații:'));
  assert.ok(html.includes('IANA rezervă exemplu.net pentru documentație.'));
  assert.ok(html.includes('încredere 90%'));
  assert.ok(!html.includes('"claim_text"'));
});

test('proposed topics, script scenes and verdicts each get their own sentence', () => {
  const topics = friendlyAnswer(
    JSON.stringify({ topics: [{ title: 'Robotică autonomă', topic: 'Descoperire', angle: 'Istoric' }] }),
  );
  assert.ok(topics.includes('Îți propun 1 subiect:'));
  assert.ok(topics.includes('<strong>Robotică autonomă</strong>'));

  const script = friendlyAnswer(
    JSON.stringify({ title: 'RoBoți', scenes: [{ narration: 'Mașinile învață singure.', visual: 'hologramă' }] }),
  );
  assert.ok(script.includes('„RoBoți" — 1 scenă:'));
  assert.ok(script.includes('Mașinile învață singure.'));

  const verdict = friendlyAnswer(
    JSON.stringify({ status: 'SUPPORTED', confidence: 1, evidence_quote: 'IANA reserved it.', verifier_notes: 'Citat direct.' }),
  );
  assert.ok(verdict.includes('Verdict: susținută de sursă · încredere 100%'));
  assert.ok(verdict.includes('„IANA reserved it."'));
});

test('ordinary answers pass through as text, with no technical block', () => {
  const html = friendlyAnswer('Da, sunt funcțional și gata să te ajut.');
  assert.equal(html, 'Da, sunt funcțional și gata să te ajut.');
});

test('fenced JSON and JSON after a sentence are both recognised', () => {
  const fenced = extractJson('```json\n{"urls": []}\n```');
  assert.deepEqual(fenced, { urls: [] });
  const embedded = extractJson('Sigur. Iată alegerile:\n{"urls": [{"url": "https://a.b"}]}');
  assert.deepEqual(embedded, { urls: [{ url: 'https://a.b' }] });
  assert.equal(extractJson('Doar o frază despre roboți.'), null);
});

test('nothing of the model output reaches the page unescaped', () => {
  const html = friendlyAnswer(
    JSON.stringify({ urls: [{ url: 'https://a.b', why: '<script>alert(1)</script>' }] }),
  );
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
});

test('a generic object reads as labelled rows, with the raw JSON only collapsed', () => {
  const html = friendlyAnswer('{"day": "2026-09-11", "stages": ["preflight", "research"], "meta": {"model": "nemotron"}}');
  const visible = html.split('<details')[0];
  assert.ok(visible.includes('day:'));
  assert.ok(visible.includes('2026-09-11'));
  assert.ok(visible.includes('preflight'));
  assert.ok(!visible.includes('{') && !visible.includes('}'));
});

test('a structured answer with nothing displayable says so instead of printing braces', () => {
  const html = friendlyAnswer('{}');
  assert.ok(html.includes('fără conținut afișabil'));
  assert.ok(html.includes('Răspunsul exact al modelului'));
});

test('a truncated answer still reads as its complete items, with a note and no raw braces', () => {
  const truncated = '[{"claim_text": "IANA rezervă exemplu.net pentru documentație.", "importance": "CRITICAL"}, {"claim_text": "Subdomeniile nu pot fi înregist';
  const html = friendlyAnswer(truncated);
  assert.equal(extractJson(truncated), null);
  assert.deepEqual(salvageItems(truncated).map((one) => one.claim_text), [
    'IANA rezervă exemplu.net pentru documentație.',
  ]);
  assert.ok(html.includes('s-a întrerupt la limita de tokeni'));
  assert.ok(html.includes('IANA rezervă exemplu.net'));
  const visible = html.split('<details')[0];
  assert.ok(!visible.includes('{"'));
});

test('salvage reads objects inside a truncated wrapper and skips broken ones', () => {
  const broken = '{"urls": [{"url": "https://a.b", "why": "bun"}, {"url": "https://c.d", "why": "trunc';
  const items = salvageItems(broken);
  assert.equal(items.length, 1);
  assert.equal(items[0].url, 'https://a.b');
  const html = friendlyAnswer(broken);
  assert.ok(html.includes('Îți propun 1 pagină de citit'));
  assert.ok(html.includes('https://a.b'));
});

test('braces inside quoted strings do not confuse the salvage', () => {
  const text = '[{"claim_text": "obiectul {fals} nu contează", "text": "x"}, {"claim_text": "al doilea", "text": "y"}';
  const items = salvageItems(text);
  assert.equal(items.length, 2);
  assert.equal(items[0].claim_text, 'obiectul {fals} nu contează');
});
