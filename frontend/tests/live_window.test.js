import test from 'node:test';
import assert from 'node:assert/strict';
import { eventMatchesAgent, nowLine } from '../src/live_window.js';

const ID = '4df0b539-49dc-41aa-b68f-748c67d87532';

test('an agent event matches by aggregate, by payload, and by message participation', () => {
  assert.ok(eventMatchesAgent({ event_type: 'agent.state_changed', aggregate_id: ID, payload: {} }, ID));
  assert.ok(eventMatchesAgent({ event_type: 'agent.run_completed', payload: { agent_id: ID } }, ID));
  assert.ok(
    eventMatchesAgent(
      { event_type: 'agent.message_posted', aggregate_id: 'm-1', payload: { from_agent_id: ID } },
      ID,
    ),
  );
  assert.ok(
    eventMatchesAgent(
      { event_type: 'agent.message_posted', aggregate_id: 'm-1', payload: { to_agent_id: ID } },
      ID,
    ),
  );
});

test('events that belong to someone else — or to no one — do not match', () => {
  assert.ok(
    !eventMatchesAgent({ event_type: 'agent.state_changed', aggregate_id: 'other', payload: {} }, ID),
  );
  // A production event does not name an employee, even when its payload mentions the task.
  assert.ok(
    !eventMatchesAgent({ event_type: 'factual.claim_extracted', payload: { claim_text: 'x' } }, ID),
  );
  assert.ok(!eventMatchesAgent(null, ID));
  assert.ok(!eventMatchesAgent({ event_type: 'agent.state_changed', aggregate_id: ID }, ''));
});

test('the now-line reads the state a person would name', () => {
  assert.equal(nowLine('THINKING', 'research_and_verification'), 'working on the task research and verification');
  assert.equal(nowLine('THINKING', null), 'working');
  assert.equal(nowLine('IDLE', null), 'no task right now');
  assert.equal(nowLine('PAUSED', null), 'paused');
});
