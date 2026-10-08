import test from 'node:test';
import assert from 'node:assert/strict';
import { runtimeLabel, runDoneLine, taskLabel, statusLabel, describeEvent } from '../src/ledger.js';
import { OfficeState } from '../src/office_state.js';
import { bubblePages } from '../src/speech_bubble.js';

/*
 * The scene speaks Romanian. The canvas once printed raw enums over the employees' heads and on
 * the render bay's wall: «COMPLETED: GATHER_SOURCES ✓», «RANDARE / IDLE», «Kael · WORKING».
 * What the scene draws now goes through the register's own labels; the backend's sentences
 * reach the bubble untouched.
 */

test('a runtime state reads as the page words it, for either gender', () => {
  assert.equal(runtimeLabel('WORKING'), 'în lucru');
  assert.equal(runtimeLabel('IDLE'), 'în așteptare');
  assert.equal(runtimeLabel('THINKING'), 'se gândește');
  assert.equal(runtimeLabel('PAUSED'), 'în pauză');
  assert.equal(runtimeLabel('BLOCKED'), 'blocaj');
  assert.equal(runtimeLabel('ERROR'), 'eroare');
  assert.equal(runtimeLabel(''), 'în așteptare', 'no state is the idle one, as stateOf says');
  assert.equal(runtimeLabel('SOMETHING_NEW'), 'something new', 'an unknown state reads as its own words');
  for (const s of ['WORKING', 'IDLE', 'THINKING', 'PAUSED', 'BLOCKED', 'ERROR']) assert.doesNotMatch(runtimeLabel(s), /[A-Z_]/, s);
});

test('a finished run says so in the words of the register row beside it', () => {
  assert.equal(runDoneLine({ status: 'SUCCEEDED', task_type: 'gather_sources' }), 'Sarcină reușită: căutarea surselor');
  assert.equal(runDoneLine({ status: 'SUCCEEDED' }), 'Sarcină reușită');
  assert.equal(runDoneLine({ status: 'SUCCEEDED', task_type: 'brand_new_type' }), 'Sarcină reușită: brand new type');
  const row = describeEvent({ event_type: 'agent.run_completed', payload: { status: 'SUCCEEDED', task_type: 'gather_sources' } });
  assert.equal(row.label, `sarcină ${statusLabel('SUCCEEDED')}`, 'the register and the bubble agree');
  assert.equal(taskLabel('reconcile_day'), 'închiderea zilei');
});

test('the scene bubble: the Romanian line on a finished run, the backend words untouched, nothing invented', () => {
  const state = new OfficeState();
  state.initFromLayout({ zones: [], assignments: [{ agent_id: 'a1', display_name: 'Elena', runtime_state: 'WORKING' }] });
  state.handleDomainEvent({ event_type: 'agent.run_completed', payload: { agent_id: 'a1', status: 'SUCCEEDED', task_type: 'gather_sources' } });
  assert.equal(state.speechBubbles.length, 1);
  assert.equal(state.speechBubbles[0].text, 'Sarcină reușită: căutarea surselor ✓');
  const words = bubblePages(state.speechBubbles[0].text).flat().join(' ');
  assert.doesNotMatch(words, /COMPLETED|GATHER_SOURCES/);
  assert.match(words, /SARCINĂ REUȘITĂ/);

  state.handleDomainEvent({ event_type: 'agent.message_sent', aggregate_id: 'a1', payload: { text: 'Am găsit trei surse primare.' } });
  assert.equal(state.speechBubbles[0].text, 'Am găsit trei surse primare.', 'the backend sentence, as written');

  const quiet = new OfficeState();
  quiet.initFromLayout({ zones: [], assignments: [{ agent_id: 'a2', display_name: 'Kael' }] });
  quiet.handleDomainEvent({ event_type: 'agent.message_sent', aggregate_id: 'a2', payload: {} });
  assert.equal(quiet.speechBubbles.length, 0, 'a message with no text puts no invented words in anyone\'s mouth');
});

test('a replayed event moves the scene but puts no bubble up: history is not told as if said now', () => {
  const state = new OfficeState();
  state.initFromLayout({ zones: [], assignments: [{ agent_id: 'a1', display_name: 'Elena', runtime_state: 'WORKING' }] });
  state.handleDomainEvent({ event_type: 'agent.run_completed', payload: { agent_id: 'a1', status: 'SUCCEEDED', task_type: 'gather_sources' } }, false);
  state.handleDomainEvent({ event_type: 'agent.message_sent', aggregate_id: 'a1', payload: { text: 'Am găsit trei surse primare.' } }, false);
  assert.equal(state.speechBubbles.length, 0, 'no bubble from the replay');
  assert.equal(state.agents[0].runtime_state, 'WORKING', 'a completed run does not overwrite the employee state');
  state.handleDomainEvent({ event_type: 'agent.state_changed', aggregate_id: 'a1', payload: { runtime_state: 'IDLE' } }, false);
  assert.equal(state.agents[0].runtime_state, 'IDLE', 'the authoritative state event is applied');
  state.handleDomainEvent({ event_type: 'agent.message_sent', aggregate_id: 'a1', payload: { text: 'Acum.' } }, true);
  assert.equal(state.speechBubbles.length, 1, 'a live event still speaks');
});
