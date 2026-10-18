import test from 'node:test';
import assert from 'node:assert/strict';
import {
  APPROVALS_PATH,
  APPROVAL_DECISION_PATH,
  AUTONOMY_MODES,
  MODE_MEANING,
  approvalCostText,
  approvalDecisionCommand,
  approvalExpiryText,
  autonomyModeCommand,
  autonomyModeLabel,
  autonomyModeMeaning,
  promotionBlockedReason,
  readApprovals,
  referenceSetSummary,
  riskTierMeaning,
} from '../src/governance.js';

test('the three modes are the three the backend accepts, each with its own sentence', () => {
  assert.deepEqual(AUTONOMY_MODES, ['MANUAL', 'SUPERVISED', 'AUTONOMOUS_CEO']);
  for (const mode of AUTONOMY_MODES) {
    assert.ok(MODE_MEANING[mode].length > 40, `${mode} has no sentence`);
    assert.equal(autonomyModeMeaning(mode), MODE_MEANING[mode]);
    assert.ok(autonomyModeLabel(mode));
  }
});

test('a mode the page does not know is named, never explained away', () => {
  assert.match(autonomyModeMeaning('LUNAR'), /nu cunoaște|necunoscut/i);
  assert.equal(autonomyModeLabel('LUNAR'), 'LUNAR');
  assert.equal(autonomyModeLabel(null), '—');
});

test('the command carries the version the snapshot was read at', () => {
  const command = autonomyModeCommand({ version: 7 }, 'SUPERVISED', 'fixed-id');
  assert.deepEqual(command, {
    schema_version: 1,
    command_id: 'fixed-id',
    expected_version: 7,
    autonomy_mode: 'SUPERVISED',
  });
});

test('a command is never built without a version or with an invented mode', () => {
  assert.throws(() => autonomyModeCommand({ version: 0 }, 'MANUAL', 'id'));
  assert.throws(() => autonomyModeCommand({}, 'MANUAL', 'id'));
  assert.throws(() => autonomyModeCommand({ version: 3 }, 'FULL_SEND', 'id'));
});

test('while the studio is stopped the page refuses a promotion before sending it', () => {
  const stopped = { version: 3, autonomy_stopped: true, autonomy_mode: 'MANUAL' };
  const reason = promotionBlockedReason(stopped, 'AUTONOMOUS_CEO');
  assert.match(String(reason), /OPRIT/i);
  // Lowering is always allowed, and a stop never blocks the safer choice.
  assert.equal(promotionBlockedReason(stopped, 'MANUAL'), null);
  assert.equal(
    promotionBlockedReason({ version: 3, autonomy_stopped: true, autonomy_mode: 'AUTONOMOUS_CEO' }, 'SUPERVISED'),
    null,
  );
  // A running studio is the server's decision to make: SAFE_MODE is not in the snapshot.
  assert.equal(
    promotionBlockedReason({ version: 3, autonomy_stopped: false, autonomy_mode: 'MANUAL' }, 'SUPERVISED'),
    null,
  );
});

test('the approvals answer is read whichever container it arrives in', () => {
  const row = {
    id: 'a1',
    action: 'publishing.public_publish',
    risk_tier: 'T3',
    requester: 'runbook.publish',
    cost_usd: null,
    reversible: false,
    expires_at: '2026-09-19T08:00:00+00:00',
    result: 'PENDING',
  };
  assert.equal(readApprovals({ approvals: [row] })[0].id, 'a1');
  assert.equal(readApprovals({ requests: [row] })[0].id, 'a1');
  assert.equal(readApprovals([row])[0].id, 'a1');
  assert.deepEqual(readApprovals(null), []);
  assert.deepEqual(readApprovals({ approvals: 'soon' }), []);
});

test('only what is still waiting is shown, and an unpriced request stays unpriced', () => {
  const rows = readApprovals({
    approvals: [
      {
        id: 'a1',
        action: 'agent.fire',
        action_label: 'Concedierea unui angajat',
        subject: 'agent-7',
        risk_tier: 'T3',
        result: 'PENDING',
        cost_usd: null,
      },
      { id: 'a2', action: 'provider.activate', tier: 'T3', result: 'APPROVED', cost: 1.5 },
      { id: 'a3', action: 'agent.hire', risk_tier: 'T2', result: 'PENDING', cost_usd: 0.25 },
    ],
  });
  assert.deepEqual(
    rows.filter((r) => r.pending).map((r) => r.id),
    ['a1', 'a3'],
  );
  assert.equal(rows[0].cost_known, false);
  assert.equal(rows[0].cost_label, 'necunoscut');
  assert.equal(rows[0].cost_usd, null);
  assert.equal(rows[0].action_label, 'Concedierea unui angajat');
  assert.equal(rows[0].subject, 'agent-7');
  assert.equal(rows[1].risk_tier, 'T3');
  // A row with no label of its own still names the action, never an empty headline.
  assert.equal(rows[1].action_label, 'provider.activate');
  assert.equal(rows[2].cost_known, true);
});

test('a cost the studio could not compute reads «necunoscut», and zero reads zero', () => {
  assert.equal(approvalCostText(null), 'necunoscut');
  assert.equal(approvalCostText(undefined), 'necunoscut');
  assert.equal(approvalCostText('1.0'), 'necunoscut');
  assert.equal(approvalCostText(Number.NaN), 'necunoscut');
  assert.equal(approvalCostText(0), '0,00 USD');
  assert.equal(approvalCostText(1.5), '1,50 USD');
  assert.equal(approvalCostText(0.004), '0,004 USD');
});

test('the expiry is read as time left, and an aged request says it expired', () => {
  const now = Date.parse('2026-09-18T10:00:00Z');
  assert.match(approvalExpiryText('2026-09-19T08:00:00+00:00', now), /22 h/);
  assert.match(approvalExpiryText('2026-09-18T10:30:00+00:00', now), /30 min/);
  assert.match(approvalExpiryText('2026-09-18T09:00:00+00:00', now), /expirat/);
  assert.equal(approvalExpiryText('not a date', now), 'termen necunoscut');
  assert.equal(approvalExpiryText(null, now), 'termen necunoscut');
});

test('every risk tier of document 31 has a sentence the Owner can read', () => {
  for (const tier of ['T0', 'T1', 'T2', 'T3', 'T4']) {
    assert.ok(riskTierMeaning(tier).length > 10, `${tier} has no sentence`);
  }
  assert.match(riskTierMeaning('T9'), /necunoscut/i);
});

test('the answer names the request it answers and carries nothing the command forbids', () => {
  assert.deepEqual(approvalDecisionCommand('a1', 'APPROVED', 'fixed-id'), {
    schema_version: 1,
    command_id: 'fixed-id',
    approval_id: 'a1',
    decision: 'APPROVED',
  });
  assert.equal(approvalDecisionCommand('a1', 'REFUSED', 'fixed-id').decision, 'REFUSED');
  assert.equal(approvalDecisionCommand('a1', 'REFUSED', 'fixed-id', 'nu acum').note, 'nu acum');
  assert.throws(() => approvalDecisionCommand('a1', 'MAYBE', 'fixed-id'));
  assert.throws(() => approvalDecisionCommand('', 'APPROVED', 'fixed-id'));
});

test('the approvals routes live in one place', () => {
  assert.equal(APPROVALS_PATH, '/owner/approvals');
  assert.equal(APPROVAL_DECISION_PATH, '/owner/approvals/decision');
});

test('the reference slots are read from the bible, filled and empty apart', () => {
  const summary = referenceSetSummary({
    reference_assets_json: { portrait: 'asset-1', full_body: null, front: null, side: null, back: null },
  });
  assert.equal(summary.total, 5);
  assert.equal(summary.filled, 1);
  assert.equal(summary.complete, false);
  assert.deepEqual(
    summary.slots.filter((s) => s.filled).map((s) => s.slot),
    ['portrait'],
  );
  assert.ok(summary.slots[0].label);
});

test('a character with no slots declared is shown the slots the studio produces', () => {
  const summary = referenceSetSummary({ reference_assets_json: {} });
  assert.equal(summary.total, 5);
  assert.equal(summary.filled, 0);
  assert.equal(referenceSetSummary({}).total, 5);
  assert.equal(referenceSetSummary(null).filled, 0);
});

test('a complete set is complete only when every declared slot holds an asset', () => {
  const summary = referenceSetSummary({
    reference_assets_json: { portrait: 'a', full_body: 'b', front: 'c', side: 'd', back: 'e' },
  });
  assert.equal(summary.complete, true);
  assert.equal(summary.filled, 5);
});

// ------------------------------------------------ PAGE_OWNER_DAY: the cards, the rule, the switches

const FILM = '3ec1740c-0000-4000-8000-000000000001';
const NOW = Date.parse('2026-10-02T08:00:00Z');
/** @param {any} row */
const card = (row, extra = {}) => approvalCardHtmlOf(readApprovalsOf([{ result: 'PENDING', expires_at: '2026-10-04T08:00:00Z', ...row }])[0], { now: NOW, escape: escapeOf, caveat: '', tierMeaning: '', ...extra });
let approvalCardHtmlOf;
let readApprovalsOf;
let escapeOf;
let gov;
test.before(async () => {
  gov = await import('../src/governance.js');
  approvalCardHtmlOf = gov.approvalCardHtml;
  readApprovalsOf = gov.readApprovals;
  escapeOf = (await import('../src/html.js')).escapeHtml;
});

test('a paid media card opens the sheet and can be refused, but is never approved in one click', () => {
  const html = card({ id: 'a-1', action: 'media.motion_purchase', action_label: 'Mișcarea filmului', subject: FILM, risk_tier: 'T3', cost_usd: 27.2, cost_label: 'plafon 27.2 USD', context: { step: 'motion', plan_hash: 'abcdef012345', storyboard_id: FILM }, film_title: 'Nepal plătește' });
  assert.ok(!html.includes('data-decision="APPROVED"'), 'no one-click yes for a purchase');
  assert.ok(html.includes(`data-sheet-open="${FILM}"`));
  assert.ok(html.includes('Deschide foaia de filmare'));
  assert.ok(html.includes('data-decision="REFUSED"'));
  // the film by its title, not by its id; the step and the plan beside it
  assert.ok(html.includes('Nepal plătește'));
  assert.ok(html.includes('mișcarea'));
  assert.ok(html.includes('abcdef012345'));
  assert.equal(gov.isSheetQuestion(readApprovalsOf([{ action: 'media.stills_purchase', subject: FILM, result: 'PENDING' }])[0]), true);
  assert.equal(gov.isSheetQuestion(readApprovalsOf([{ action: 'publishing.public_publish', subject: FILM, result: 'PENDING' }])[0]), false);
});

test('a T3 or T4 card asks first: its cost, his note and «Da, aprob»', () => {
  const row = { id: 'a-2', action: 'publishing.public_publish', action_label: 'Publicare publică', subject: 'film', risk_tier: 'T3', cost_usd: null };
  const closed = card(row);
  assert.ok(!closed.includes('data-decision="APPROVED"'), 'the first press only opens the question');
  assert.ok(closed.includes('data-decision="CONFIRM"'));
  const open = card(row, { confirming: true });
  assert.ok(open.includes('data-decision="APPROVED"'));
  assert.ok(open.includes('Da, aprob'));
  assert.ok(open.includes('data-approval-note'));
  assert.ok(open.includes('necunoscut'), 'the cost is said in the question');
  assert.ok(open.includes('data-decision="CANCEL"'));
  // a T2 internal request keeps its one key
  const t2 = card({ id: 'a-3', action: 'agent.hire', risk_tier: 'T2', cost_usd: 0.25 });
  assert.ok(t2.includes('data-decision="APPROVED"'));
});

const POLICY = { version: 4, environment: 'PRODUCTION', autonomy_stopped: false, autonomy_mode: 'AUTONOMOUS_CEO', paid_media_approval: 'MODE', paid_media_approval_over_usd: null };
const BUDGET = { budgets: [{ period: 'DAILY', active: true, limit_usd: '15' }], versions: { DAILY: 1 } };
const JOB = { workflow_type: 'DAILY_RUN', is_active: true, run_at_local: '05:00' };

test('what the next run buys alone, for every rule, mode and budget', () => {
  const words = (/** @type {any} */ policy, /** @type {any} */ budget = BUDGET, /** @type {any} */ job = JOB) => gov.dayWillWords({ ...POLICY, ...policy }, budget, job);
  assert.equal(words({}), 'La următoarea rulare (05:00): studioul cumpără singur până la plafonul foii și bugetul de 15,00 USD: imaginile, cadrul de probă și, după ce controlul clipului îl acceptă, restul mișcării.');
  assert.match(words({ paid_media_approval: 'EVERY_PAID_STEP' }), /se oprește la imagini și te întreabă/);
  assert.match(words({ paid_media_approval: 'OVER_USD', paid_media_approval_over_usd: 5 }), /cel mult 5,00 USD.*bugetul de 15,00 USD.*te întreabă/);
  for (const rule of ['MODE', 'OVER_USD', 'EVERY_PAID_STEP']) {
    const over = rule === 'OVER_USD' ? 5 : null;
    assert.match(words({ paid_media_approval: rule, paid_media_approval_over_usd: over, autonomy_mode: 'MANUAL' }), /nu cumpără nimic singur/, `${rule} MANUAL`);
    assert.match(words({ paid_media_approval: rule, paid_media_approval_over_usd: over, autonomy_mode: 'SUPERVISED' }), /te întreabă/, `${rule} SUPERVISED`);
    assert.match(words({ paid_media_approval: rule, paid_media_approval_over_usd: over, environment: 'TEST' }), /mediul TEST.*nu cumpără nimic/, `${rule} TEST`);
    assert.match(words({ paid_media_approval: rule, paid_media_approval_over_usd: over, autonomy_stopped: true }), /oprită/, `${rule} stopped`);
  }
  // no daily budget: in PRODUCTION nothing is bought unasked
  assert.match(words({}, { budgets: [] }), /fără un buget zilnic activ.*nu cumpără nimic singur/);
  assert.match(words({ paid_media_approval: 'OVER_USD', paid_media_approval_over_usd: 5 }, { budgets: [{ period: 'DAILY', active: false, limit_usd: '15' }] }), /fără un buget zilnic activ/);
  // not read is not none
  assert.match(words({}, null), /bugetul zilnic nu a fost citit/);
  // the schedule off: what a run he starts would do
  assert.match(words({}, BUDGET, { ...JOB, is_active: false }), /^Programarea zilnică este oprită; la o rulare pornită de tine: /);
  assert.match(words({}, BUDGET, [JOB]), /^La următoarea rulare \(05:00\)/, 'the jobs list is read too');
  for (const rule of ['MODE', 'OVER_USD', 'EVERY_PAID_STEP']) {
    assert.ok(!/\b[a-z]+_[a-z_]+\b/.test(words({ paid_media_approval: rule, paid_media_approval_over_usd: 3 })), 'no code in his sentence');
  }
});

test('a switch that lets the studio spend asks first, with what the next run will do', () => {
  const manual = { ...POLICY, autonomy_mode: 'MANUAL' };
  const facts = { policy: manual, budget: BUDGET, job: JOB, preflight: null };
  const promote = gov.consequenceWords(facts, { mode: 'AUTONOMOUS_CEO' });
  assert.equal(promote?.question, 'Treci studioul în modul «CEO autonom»?');
  assert.match(String(promote?.words), /La următoarea rulare \(05:00\): studioul cumpără singur/);
  assert.match(String(promote?.words), /Distribuție/);
  assert.equal(promote?.yes, 'Da, trec în CEO autonom');
  const prod = gov.consequenceWords({ ...facts, policy: { ...POLICY, environment: 'TEST' } }, { environment: 'PRODUCTION' });
  assert.equal(prod?.question, 'Treci studioul în mediul PRODUCTION?');
  assert.match(String(prod?.words), /cumpără singur/);
  const job = gov.consequenceWords({ ...facts, policy: POLICY, job: { ...JOB, is_active: false } }, { dailyJob: true });
  assert.equal(job?.question, 'Pornești programarea zilnică?');
  assert.match(String(job?.words), /^La următoarea rulare \(05:00\)/);
  const run = gov.consequenceWords({ ...facts, policy: POLICY, preflight: { status: 'BLOCKED', checks: [{ ok: false, severity: 'BLOCKING', message: 'Autonomia studioului este oprită.' }] } }, { runNow: true });
  assert.equal(run?.question, 'Pornești rularea de azi acum?');
  assert.match(String(run?.words), /^Rularea de azi: /);
  assert.match(String(run?.words), /Verificarea preliminară ar opri ziua: Autonomia studioului este oprită\./);
  assert.equal(run?.yes, 'Da, pornește rularea');
});

test('lowering the mode, going back to TEST and switching the schedule off ask nothing', () => {
  const facts = { policy: POLICY, budget: BUDGET, job: JOB, preflight: null };
  assert.equal(gov.consequenceWords(facts, { mode: 'MANUAL' }), null);
  assert.equal(gov.consequenceWords(facts, { mode: 'SUPERVISED' }), null);
  assert.equal(gov.consequenceWords(facts, { environment: 'TEST' }), null);
  assert.equal(gov.consequenceWords(facts, { dailyJob: false }), null);
  assert.equal(gov.consequenceWords(facts, { mode: 'AUTONOMOUS_CEO' }), null, 'the mode it is already in');
});

test('detailed governance controls stay in the autonomy dialog, out of the compact dashboard', async () => {
  const fs = await import('node:fs');
  const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const panel = html.slice(html.indexOf('id="dashboard-governance-controls"'), html.indexOf('id="autonomy-overview"'));
  assert.ok(html.indexOf('id="autonomy-modal"') < html.indexOf('id="dashboard-governance-controls"'));
  assert.ok(panel.includes('id="paid-media-governance"'), 'existing rule form remains in configuration');
  assert.ok(panel.includes('id="day-will"'), 'what the next run will do');
  const main = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  assert.ok(main.includes('dayWillWords('));
  assert.ok(main.includes('consequenceWords('));
  assert.ok(main.includes('paidMediaFormHtml(state.policy'));
});
