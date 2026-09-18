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
  assert.equal(approvalCostText(0), '0.00 USD');
  assert.equal(approvalCostText(1.5), '1.50 USD');
  assert.equal(approvalCostText(0.004), '0.004 USD');
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
