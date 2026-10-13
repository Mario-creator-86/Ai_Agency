// PAGE_SETTINGS_ERRORS (PAGE-10, PUB-11, PUB-12): a channel's publish policy (how the studio's own
// uploads are released, whether public is allowed at all, the delay) could be changed only by
// calling the API by hand, and an «unlisted» upload read «Public» on the page. These are the pure
// pieces the page builds the form, its question, its answer and the badges from.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  gateChecksHtml,
  privacyBadgeHtml,
  privacyWord,
  publishPolicyAnswer,
  publishPolicyCommand,
  publishPolicyQuestion,
  publishPolicyWords,
  quickPublishQuestion,
  resolvePublicationCommand,
  RESOLVABLE_STATES,
  demoCaseShown,
} from '../src/owner_controls.js';

const CHANNEL = {
  id: 'ch-1',
  channel_name: 'Canalul A',
  channel_type: 'MAIN_FACTUAL',
  autonomous_privacy: 'private',
  public_publish_enabled: false,
  publish_delay_minutes: 0,
  policy_version: 4,
};

test('the privacy badge says private, unlisted and public as three different words', () => {
  assert.equal(privacyWord('private'), 'Privat');
  assert.equal(privacyWord('unlisted'), 'Nelistat');
  assert.equal(privacyWord('public'), 'Public');
  assert.equal(privacyWord('something'), '—');
  assert.match(privacyBadgeHtml('unlisted'), /privacy-badge-unlisted[^>]*>Nelistat</);
  assert.doesNotMatch(privacyBadgeHtml('unlisted'), /Public/);
  assert.match(privacyBadgeHtml('private'), /privacy-badge-private[^>]*>Privat</);
  assert.match(privacyBadgeHtml('public'), /privacy-badge-public[^>]*>Public</);
  // what YouTube reports, when it differs from what was asked, is said beside it
  assert.match(privacyBadgeHtml('public', 'private'), /YouTube: Privat/);
  assert.doesNotMatch(privacyBadgeHtml('public', 'public'), /YouTube:/);
});

test('the policy is said in his words, with correct plurals for the delay', () => {
  assert.equal(
    publishPolicyWords(CHANNEL),
    'Încărcările făcute singur de studio: privat · publicul nu este permis · fără întârziere · versiunea 4.',
  );
  assert.match(publishPolicyWords({ ...CHANNEL, publish_delay_minutes: 1 }), /întârziere de 1 minut ·/);
  assert.match(publishPolicyWords({ ...CHANNEL, publish_delay_minutes: 19 }), /întârziere de 19 minute ·/);
  assert.match(publishPolicyWords({ ...CHANNEL, publish_delay_minutes: 20 }), /întârziere de 20 de minute ·/);
  assert.match(publishPolicyWords({ ...CHANNEL, autonomous_privacy: 'unlisted', public_publish_enabled: true }), /nelistat · publicul este permis/);
});

test('the versioned command carries only what he changed, his id and the version the page read', () => {
  const built = publishPolicyCommand(CHANNEL, { privacy: 'unlisted', publicAllowed: false, delay: '0' }, 'cmd-1');
  assert.deepEqual(built, { command: { command_id: 'cmd-1', expected_version: 4, autonomous_privacy: 'unlisted' } });
  const all = publishPolicyCommand(CHANNEL, { privacy: 'public', publicAllowed: true, delay: '30' }, 'cmd-2');
  assert.deepEqual(all, {
    command: { command_id: 'cmd-2', expected_version: 4, autonomous_privacy: 'public', public_publish_enabled: true, publish_delay_minutes: 30 },
  });
});

test('a form the backend would refuse is stopped before anything is sent, in Romanian', () => {
  const refused = (form) => /** @type {any} */ (publishPolicyCommand(CHANNEL, form, 'c')).error;
  assert.match(refused({ privacy: 'private', publicAllowed: false, delay: '0' }), /Nu ai schimbat nimic/);
  assert.match(refused({ privacy: 'public', publicAllowed: false, delay: '0' }), /publicul permis/);
  for (const delay of ['', '-1', '2,5', 'zece', '43201']) {
    assert.match(refused({ privacy: 'private', publicAllowed: false, delay }), /minute/, delay);
  }
  assert.match(refused({ privacy: 'secret', publicAllowed: false, delay: '0' }), /vizibilitate/);
  // a channel the page has not read is not changed blindly
  assert.ok('error' in publishPolicyCommand(null, { privacy: 'unlisted', publicAllowed: false, delay: '0' }, 'c'));
});

test('the question names the channel and every change; the answer is the backend\'s result', () => {
  const built = /** @type {any} */ (publishPolicyCommand(CHANNEL, { privacy: 'public', publicAllowed: true, delay: '20' }, 'c'));
  const question = publishPolicyQuestion(CHANNEL, built.command);
  assert.match(question, /Canalul A/);
  assert.match(question, /privat → public/);
  assert.match(question, /publicul permis/);
  assert.match(question, /20 de minute/);
  assert.match(question, /\?$/);
  assert.equal(
    publishPolicyAnswer({ status: 'COMMITTED', channel: { ...CHANNEL, autonomous_privacy: 'unlisted', policy_version: 5 } }),
    'Salvat. Încărcările făcute singur de studio: nelistat · publicul nu este permis · fără întârziere · versiunea 5.',
  );
  assert.match(publishPolicyAnswer({ status: 'NO_CHANGE', channel: CHANNEL }), /^Nimic de schimbat\./);
  assert.equal(publishPolicyAnswer(null), '');
});

test('his answer about a publication the studio could not settle: the id is read from a link', () => {
  assert.deepEqual(RESOLVABLE_STATES, ['NEEDS_RECONCILIATION', 'REMOTE_UNKNOWN']);
  assert.deepEqual(resolvePublicationCommand({ found: false, video: '', commandId: 'r-1' }), { command: { command_id: 'r-1', found: false } });
  for (const video of ['dQw4w9WgXcQ', 'https://www.youtube.com/shorts/dQw4w9WgXcQ', 'https://youtube.com/watch?v=dQw4w9WgXcQ&t=1', 'https://youtu.be/dQw4w9WgXcQ']) {
    assert.deepEqual(resolvePublicationCommand({ found: true, video, commandId: 'r-2' }), {
      command: { command_id: 'r-2', found: true, remote_video_id: 'dQw4w9WgXcQ' },
    }, video);
  }
  assert.match(/** @type {any} */ (resolvePublicationCommand({ found: true, video: '', commandId: 'r' })).error, /ID-ul videoclipului/);
  assert.match(/** @type {any} */ (resolvePublicationCommand({ found: true, video: 'not an id!', commandId: 'r' })).error, /ID-ul videoclipului/);
});

test('the gate list is the backend\'s evaluation, never a static promise', () => {
  const html = gateChecksHtml({
    eligible: false,
    checks: [
      { check_name: 'autonomy', passed: true, detail: 'Autonomia este pornită.' },
      { check_name: 'qc', passed: false, detail: 'Filmul nu a trecut <QC>.' },
    ],
  });
  assert.match(html, /Autonomia este pornită\./);
  assert.match(html, /is-passed/);
  assert.match(html, /is-failed/);
  assert.match(html, /&lt;QC&gt;/); // escaped
  assert.match(html, /nu poate fi publicat/);
  assert.match(gateChecksHtml(null), /Niciun film care să fi trecut QC/);
  assert.match(gateChecksHtml({ eligible: true, checks: [] }), /poate fi publicat/);
});

test('quick publish asks with the film, the channel and the privacy named', () => {
  assert.equal(
    quickPublishQuestion({ title: 'Nepal și criza', channel: 'Canalul A', privacy: 'private' }),
    'Încarci «Nepal și criza» pe «Canalul A», privat?',
  );
});

test('«Creează un caz demo» is offered only in TEST, never in PRODUCTION or before the policy is read', () => {
  assert.equal(demoCaseShown({ environment: 'TEST' }), true);
  assert.equal(demoCaseShown({ environment: 'PRODUCTION' }), false);
  assert.equal(demoCaseShown(null), false);
  assert.equal(demoCaseShown({}), false);
});
