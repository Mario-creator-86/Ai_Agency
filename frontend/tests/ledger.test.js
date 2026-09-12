import test from 'node:test';
import assert from 'node:assert/strict';
import { describeEvent, productionStatus } from '../src/ledger.js';

const names = { 'a-1': 'Dr. Aris (Researcher)', 'a-2': 'Sarah (Director)' };

test('what an employee said is shown with its name and text, as speech', () => {
  const item = describeEvent(
    { event_type: 'agent.message_sent', aggregate_id: 'a-1', payload: { text: 'Am citit patru pagini.' } },
    names,
  );
  assert.deepEqual(item, { who: 'Dr. Aris (Researcher)', label: 'said', text: 'Am citit patru pagini.', kind: 'speech' });
});

test('a typed message shows its intent and subject, and the sender by name', () => {
  const item = describeEvent(
    { event_type: 'agent.message_posted', aggregate_id: 'm-1', payload: { intent: 'ESCALATE', subject: 'Publication HOLD', from_name: 'Vera (Publisher)' } },
    names,
  );
  assert.equal(item.who, 'Vera (Publisher)');
  assert.equal(item.label, 'writes · escalation');
  assert.equal(item.text, 'Publication HOLD');
  assert.equal(item.to, 'Director');
  assert.equal(item.thread, 'm-1');
});

test('work, production, money and owner events get plain labels and the right kind', () => {
  assert.equal(describeEvent({ event_type: 'agent.state_changed', aggregate_id: 'a-2', payload: { runtime_state: 'THINKING', task_type: 'director_review' } }, names).label, 'working');
  const stage = describeEvent({ event_type: 'workflow.created', payload: { current_stage: 'SCRIPTING' } });
  assert.equal(stage.kind, 'production');
  assert.equal(stage.text, 'stage: Script');
  const cost = describeEvent({ event_type: 'economy.provider_cost_recorded', payload: { provider: 'elevenlabs', status: 'ESTIMATED', vr: '0.45' } });
  assert.equal(cost.kind, 'money');
  assert.equal(cost.text, 'elevenlabs · 0.45 VR$');
  assert.equal(describeEvent({ event_type: 'autonomy.stop_cleared', payload: {} }).kind, 'owner');
});

test('production work without a model reads as work, and says what is being made', () => {
  const working = describeEvent({ event_type: 'agent.state_changed', aggregate_id: 'a-3', payload: { runtime_state: 'WORKING', task_type: 'synthesize_voice', detail: 'vocea scenei 3' } }, { 'a-3': 'Lyra (Voice Artist)' });
  assert.equal(working.who, 'Lyra (Voice Artist)');
  assert.equal(working.label, 'working');
  assert.equal(working.text, 'vocea scenei 3');
  const done = describeEvent({ event_type: 'agent.state_changed', aggregate_id: 'a-3', payload: { runtime_state: 'IDLE', task_type: 'synthesize_voice' } }, { 'a-3': 'Lyra (Voice Artist)' });
  assert.equal(done.label, 'finished');
});

test('an unknown event still reads as words, with its first payload fields', () => {
  const item = describeEvent({ event_type: 'vendorshop.order_placed', payload: { vendor: 'acme', total: 12, nested: { a: 1 } } });
  assert.equal(item.label, 'order placed');
  assert.equal(item.text, 'vendor: acme · total: 12');
  assert.equal(item.kind, 'system');
});

test('long text is cut with an ellipsis so one entry cannot swallow the column', () => {
  const item = describeEvent({ event_type: 'agent.message_sent', payload: { text: 'x'.repeat(500) } });
  assert.equal(item.text.length, 160);
  assert.ok(item.text.endsWith('…'));
});

test('production status reads the newest stage and the last daily run', () => {
  const events = [
    { event_type: 'agent.message_sent', payload: {} },
    { event_type: 'runbook.daily_run_finished', payload: { status: 'PARTIAL' } },
    { event_type: 'workflow.job_activated', payload: { current_stage: 'QUALITY_CONTROL' } },
    { event_type: 'workflow.created', payload: { current_stage: 'RESEARCH' } },
  ];
  const status = productionStatus(events);
  assert.equal(status.stage, 'QUALITY_CONTROL');
  assert.equal(status.text, 'Production: Quality control · last daily run partial');
  assert.equal(productionStatus([]).text, 'No production in progress.');
});

test('a stage of the daily run is named in words, with its place in the day', () => {
  const started = describeEvent({
    event_type: 'runbook.stage_started',
    payload: { stage: 'script_and_storyboard', index: 6, total: 12 },
  });
  assert.equal(started.label, 'stage started');
  assert.equal(started.text, 'script and storyboard (6/12)');
  assert.equal(started.kind, 'production');

  const finished = describeEvent({
    event_type: 'runbook.stage_finished',
    payload: { stage: 'publish', status: 'SKIPPED', reason: 'Niciun canal legat.' },
  });
  assert.equal(finished.label, 'stage skipped');
  assert.equal(finished.text, 'publishing — Niciun canal legat.');
});

test('the head line says which stage the day is in while it is in it', () => {
  const running = productionStatus([
    { event_type: 'runbook.stage_started', payload: { stage: 'media', index: 7, total: 12 } },
    { event_type: 'runbook.daily_run_started', payload: { stages: 12 } },
    { event_type: 'runbook.daily_run_finished', payload: { status: 'PARTIAL' } },
  ]);
  assert.equal(running.running, 'media');
  assert.equal(running.text, 'Now: media production · last daily run partial');

  // A stage that has finished is not where the day is; only the run's own outcome remains.
  const between = productionStatus([
    { event_type: 'runbook.stage_finished', payload: { stage: 'media', status: 'COMPLETED' } },
    { event_type: 'runbook.stage_started', payload: { stage: 'media' } },
    { event_type: 'runbook.daily_run_finished', payload: { status: 'COMPLETED' } },
  ]);
  assert.equal(between.running, null);
  assert.equal(between.text, 'Last daily run completed');
});

test('a letter names both ends, says what kind it is, and carries its thread', () => {
  const item = describeEvent(
    {
      event_type: 'agent.message_posted',
      aggregate_id: 'm-9',
      payload: {
        intent: 'REQUEST_INFO',
        subject: 'Sursa cifrei de 40%',
        from_agent_id: 'a-2',
        from_name: 'Sarah (Director)',
        to_name: 'Elena (Fact Checker)',
        thread_id: 't-1',
        excerpt: 'Elena, pe ce stă 40%?',
      },
    },
    names,
  );
  assert.equal(item.who, 'Sarah (Director)');
  assert.equal(item.to, 'Elena (Fact Checker)');
  assert.equal(item.label, 'writes · question');
  assert.equal(item.text, 'Sursa cifrei de 40% — Elena, pe ce stă 40%?');
  assert.equal(item.thread, 't-1');
  const reply = describeEvent({
    event_type: 'agent.message_posted',
    aggregate_id: 'm-10',
    payload: { intent: 'STATUS', subject: 'Re: Sursa', in_reply_to: 'm-9', thread_id: 't-1' },
  });
  assert.equal(reply.label, 'replies · report');
  assert.equal(reply.who, 'Owner');
});

test('a letter to the Owner files under the Owner chip and says so', () => {
  const item = describeEvent({
    event_type: 'agent.message_posted',
    aggregate_id: 'm-11',
    payload: { intent: 'ESCALATE', subject: 'Ziua s-a oprit la etapa «media»', from_name: 'Sarah (Director)', to_name: 'Owner', for_owner: true, thread_id: 'm-11' },
  });
  assert.equal(item.kind, 'owner');
  assert.equal(item.to, 'Owner');
  assert.equal(item.forOwner, true);
  assert.equal(item.label, 'writes · escalation · TO YOU');
});
