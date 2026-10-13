import test from 'node:test';
import assert from 'node:assert/strict';
import { describeEvent, productionStatus, arrivingIds, LEDGER_SETTLE_MS } from '../src/ledger.js';

const names = { 'a-1': 'Dr. Aris (Researcher)', 'a-2': 'Sarah (Director)' };

test("the backend's sentence is the row: the employee named by the page, the sentence without the name, the portrait", () => {
  const actor = { agent_id: 'a-9', name: 'Kael (Video Editor)', role: 'VideoEditor', role_ro: 'Video Editor' };
  const arrived = describeEvent(
    {
      event_type: 'media.scene_take_recorded',
      aggregate_id: 't-1',
      payload: { storyboard_id: 'b-1', scene_number: 3, kind: 'still', status: 'PAID' },
      words_ro: 'A sosit imaginea scenei 3 din «The Zero Script Club»; Kael (Video Editor) o verifică.',
      actor,
    },
    { 'a-9': 'Kael (Video Editor)' },
  );
  assert.equal(arrived.who, 'Kael (Video Editor)');
  assert.equal(arrived.label, '');
  assert.equal(arrived.text, 'A sosit imaginea scenei 3 din «The Zero Script Club»; Kael (Video Editor) o verifică.');
  assert.equal(arrived.kind, 'production');
  assert.equal(arrived.portrait, 'a-9');
  const run = describeEvent(
    {
      event_type: 'agent.run_completed',
      payload: { agent_id: 'a-9', task_type: 'still_qc', status: 'SUCCEEDED', model_name: 'kimi-k3' },
      words_ro: 'Kael (Video Editor) a terminat verificarea unei imagini: reușită (cu kimi-k3).',
      actor,
    },
    { 'a-9': 'Kael (Video Editor)' },
  );
  assert.equal(run.who, 'Kael (Video Editor)');
  assert.equal(run.text, 'a terminat verificarea unei imagini: reușită (cu kimi-k3).');
  // Without words from the backend the page keeps its own, and no portrait is claimed.
  const bare = describeEvent(
    { event_type: 'agent.run_completed', payload: { agent_id: 'a-9', task_type: 'still_qc', status: 'SUCCEEDED', model_name: 'kimi-k3' } },
    { 'a-9': 'Kael (Video Editor)' },
  );
  assert.equal(bare.label, 'sarcină reușită');
  assert.equal(bare.portrait, undefined);
});

test('what an employee said is shown with its name and text, as speech', () => {
  const item = describeEvent(
    { event_type: 'agent.message_sent', aggregate_id: 'a-1', payload: { text: 'Am citit patru pagini.' } },
    names,
  );
  assert.deepEqual(item, { who: 'Dr. Aris (Researcher)', label: 'a spus', text: 'Am citit patru pagini.', kind: 'speech' });
});

test('a typed message shows its intent and subject, and the sender by name', () => {
  const item = describeEvent(
    { event_type: 'agent.message_posted', aggregate_id: 'm-1', payload: { intent: 'ESCALATE', subject: 'Publication HOLD', from_name: 'Vera (Publisher)' } },
    names,
  );
  assert.equal(item.who, 'Vera (Publisher)');
  assert.equal(item.label, 'scrie · escaladare');
  assert.equal(item.text, 'Publication HOLD');
  assert.equal(item.to, 'Director');
  assert.equal(item.thread, 'm-1');
});

test('work, production, money and owner events get plain labels and the right kind', () => {
  assert.equal(describeEvent({ event_type: 'agent.state_changed', aggregate_id: 'a-2', payload: { runtime_state: 'THINKING', task_type: 'director_review' } }, names).label, 'lucrează');
  const stage = describeEvent({ event_type: 'workflow.created', payload: { current_stage: 'SCRIPTING' } });
  assert.equal(stage.kind, 'production');
  assert.equal(stage.text, 'etapa: Scenariu');
  const cost = describeEvent({ event_type: 'economy.provider_cost_recorded', payload: { provider: 'elevenlabs', status: 'ESTIMATED', vr: '0.45' } });
  assert.equal(cost.kind, 'money');
  assert.equal(cost.text, 'elevenlabs · 0.45 VR$');
  assert.equal(describeEvent({ event_type: 'autonomy.stop_cleared', payload: {} }).kind, 'owner');
});

test('production work without a model reads as work, and says what is being made', () => {
  const working = describeEvent({ event_type: 'agent.state_changed', aggregate_id: 'a-3', payload: { runtime_state: 'WORKING', task_type: 'synthesize_voice', detail: 'vocea scenei 3' } }, { 'a-3': 'Lyra (Voice Artist)' });
  assert.equal(working.who, 'Lyra (Voice Artist)');
  assert.equal(working.label, 'lucrează');
  assert.equal(working.text, 'vocea scenei 3');
  const done = describeEvent({ event_type: 'agent.state_changed', aggregate_id: 'a-3', payload: { runtime_state: 'IDLE', task_type: 'synthesize_voice' } }, { 'a-3': 'Lyra (Voice Artist)' });
  assert.equal(done.label, 'a terminat');
  // W9: an error is not a finish, and the task is said in words, never as the backend's code
  const fault = describeEvent({ event_type: 'agent.state_changed', aggregate_id: 'a-3', payload: { runtime_state: 'ERROR', task_type: 'reconcile_day' } }, { 'a-3': 'Nadia (Accountant)' });
  assert.equal(fault.label, 'stare: eroare');
  assert.equal(fault.text, 'sarcina: închiderea zilei');
  assert.equal(describeEvent({ event_type: 'agent.state_changed', payload: { runtime_state: 'BLOCKED' } }).label, 'stare: blocaj');
  assert.equal(describeEvent({ event_type: 'agent.run_completed', payload: { status: 'SUCCEEDED', task_type: 'gather_sources', model_name: 'm-1' } }).text, 'căutarea surselor · m-1');
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
  assert.equal(status.text, 'Producție: Controlul calității · ultima rulare a zilei parțială');
  assert.equal(productionStatus([]).text, 'Nicio producție în lucru.');
});

test('a stage of the daily run is named in words, with its place in the day', () => {
  const started = describeEvent({
    event_type: 'runbook.stage_started',
    payload: { stage: 'script_and_storyboard', index: 6, total: 12 },
  });
  assert.equal(started.label, 'etapă începută');
  assert.equal(started.text, 'scenariu și storyboard (6/12)');
  assert.equal(started.kind, 'production');

  const finished = describeEvent({
    event_type: 'runbook.stage_finished',
    payload: { stage: 'publish', status: 'SKIPPED', reason: 'Niciun canal legat.' },
  });
  assert.equal(finished.label, 'etapă sărită');
  assert.equal(finished.text, 'publicare — Niciun canal legat.');
});

test('the head line says which stage the day is in while it is in it', () => {
  const running = productionStatus([
    { event_type: 'runbook.stage_started', payload: { stage: 'media', index: 7, total: 12 } },
    { event_type: 'runbook.daily_run_started', payload: { stages: 12 } },
    { event_type: 'runbook.daily_run_finished', payload: { status: 'PARTIAL' } },
  ]);
  assert.equal(running.running, 'media');
  assert.equal(running.text, 'Acum: producție media · ultima rulare a zilei parțială');

  // A stage that has finished is not where the day is; only the run's own outcome remains.
  const between = productionStatus([
    { event_type: 'runbook.stage_finished', payload: { stage: 'media', status: 'COMPLETED' } },
    { event_type: 'runbook.stage_started', payload: { stage: 'media' } },
    { event_type: 'runbook.daily_run_finished', payload: { status: 'COMPLETED' } },
  ]);
  assert.equal(between.running, null);
  assert.equal(between.text, 'Ultima rulare a zilei încheiată');
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
  assert.equal(item.label, 'scrie · întrebare');
  assert.equal(item.text, 'Sursa cifrei de 40% — Elena, pe ce stă 40%?');
  assert.equal(item.thread, 't-1');
  const reply = describeEvent({
    event_type: 'agent.message_posted',
    aggregate_id: 'm-10',
    payload: { intent: 'STATUS', subject: 'Re: Sursa', in_reply_to: 'm-9', thread_id: 't-1' },
  });
  assert.equal(reply.label, 'răspunde · raport');
  assert.equal(reply.who, 'Proprietar');
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
  assert.equal(item.label, 'scrie · escaladare · PENTRU TINE');
});

test('a routine job that starts is not called production', () => {
  // Measured on the Owner's studio on 2026-09-18: a restart created the model review, the
  // Director's loop and the watchdog in one second, and the ledger said "production started"
  // three times while nothing was being made - he read it as films starting on their own.
  const watchdog = describeEvent({ event_type: 'workflow.created', payload: { job_name: 'watchdog', workflow_type: 'WATCHDOG' } });
  assert.equal(watchdog.label, 'sarcină de rutină pornită');
  // W34 (updated on purpose): the backend's own word for it
  assert.equal(watchdog.text, 'supraveghetorul');
  assert.equal(watchdog.kind, 'system');
  const review = describeEvent({ event_type: 'workflow.created', payload: { job_name: 'model_review_daily', workflow_type: 'MODEL_REVIEW' } });
  assert.equal(review.label, 'sarcină de rutină pornită');
  assert.equal(review.text, 'revizuirea modelelor');
  const loop = describeEvent({ event_type: 'workflow.created', payload: { job_name: 'director_loop', workflow_type: 'DIRECTOR_LOOP' } });
  assert.equal(loop.text, 'bucla Directoarei');
  // The day itself, and a workflow that carries a stage, are still production.
  const day = describeEvent({ event_type: 'workflow.created', payload: { job_name: 'daily_main', workflow_type: 'DAILY_RUN' } });
  assert.equal(day.label, 'a început o producție');
  assert.equal(day.kind, 'production');
});

/* A row that arrives while the Owner is watching is lit once. The history that
   fills the column in the first seconds after the page opens is not news, and
   lighting it would be a flash of the whole register saying nothing. */

test('the backfill that fills the column when the page opens is not lit', () => {
  const opened = 1_000_000;
  const fresh = [{ event_id: 'e1' }, { event_id: 'e2' }];
  assert.equal(arrivingIds(fresh, opened, opened + 50).size, 0);
  assert.equal(arrivingIds(fresh, opened, opened + LEDGER_SETTLE_MS).size, 0);
});

test('an event recorded while he watches is lit, by its own id', () => {
  const opened = 1_000_000;
  const marks = arrivingIds([{ event_id: 'e7' }, { event_id: 'e8' }], opened, opened + LEDGER_SETTLE_MS + 1);
  assert.deepEqual([...marks], ['e7', 'e8']);
});

test('an event with no id is never lit, and nothing is lit from nothing', () => {
  const late = 1_000_000 + LEDGER_SETTLE_MS + 1;
  assert.equal(arrivingIds([{}, { event_id: '' }], 1_000_000, late).size, 0);
  assert.equal(arrivingIds(undefined, 1_000_000, late).size, 0);
});

test('the entry count follows the Romanian rule for «de»', async () => {
  const { entryCountLabel } = await import('../src/ledger.js');
  assert.equal(entryCountLabel(1), '1 intrare');
  assert.equal(entryCountLabel(7), '7 intrări');
  assert.equal(entryCountLabel(19), '19 intrări');
  assert.equal(entryCountLabel(20), '20 de intrări');
  assert.equal(entryCountLabel(70), '70 de intrări');
  assert.equal(entryCountLabel(101), '101 intrări');
  assert.equal(entryCountLabel(119), '119 intrări');
  assert.equal(entryCountLabel(120), '120 de intrări');
  assert.equal(entryCountLabel(200), '200 de intrări');
});

test('the tasks the studio\'s own runs record have words, and a step of a task is said as its task (W12)', async () => {
  const { taskLabel } = await import('../src/ledger.js');
  assert.equal(taskLabel('answer_mail'), 'răspunsul la corespondență');
  assert.equal(taskLabel('research_models'), 'cercetarea modelelor');
  assert.equal(taskLabel('direct_company:final'), 'conducerea companiei');
  assert.equal(taskLabel('something_new'), 'something new');
});

test('a finished sheet repair reads in Romanian, with its outcome and why', () => {
  // 2026-10-03: the Owner's activity feed read "sheet repair finished" and "status: UNRESOLVED".
  const item = describeEvent({
    event_type: 'media.sheet_repair_finished',
    timestamp: '2026-10-03T17:38:55Z',
    payload: { status: 'UNRESOLVED', reason: 'Scenariul a fost respins.' },
  });
  assert.equal(item.label, 'remedierea foii: nerezolvată');
  assert.equal(item.text, 'Scenariul a fost respins.');
  assert.ok(!/sheet repair|UNRESOLVED/.test(`${item.label} ${item.text}`));
});

test("the backend's sentence wins over the page's own line for the kinds that showed ids (2026-10-12)", () => {
  const kael = { agent_id: 'a-9', name: 'Kael (Video Editor)', role: 'VideoEditor' };
  const said = (event_type, payload, words_ro, actor = undefined) => describeEvent({ event_type, payload, words_ro, actor }, { 'a-9': 'Kael (Video Editor)' });
  const qc = said('media.qc_evaluated', { status: 'FAILED', failures: ['QC.TEXT_ON_SCREEN'] }, 'Controlul calității a picat filmul din «The Zero Script Club» (scor 0.41): text pe ecran.');
  assert.equal(qc.label, '');
  assert.equal(qc.text, 'Controlul calității a picat filmul din «The Zero Script Club» (scor 0.41): text pe ecran.');
  assert.equal(qc.kind, 'production');
  const rendered = said('media.video_rendered', { provider_name: 'ffmpeg-local' }, 'Filmul «The Zero Script Club» a fost randat (42 s).');
  assert.equal(rendered.text, 'Filmul «The Zero Script Club» a fost randat (42 s).');
  assert.equal(rendered.label, '');
  const cost = said('economy.provider_cost_recorded', { provider: 'prov-7f3a', vr: 3, status: 'BILLED' }, 'Cost facturat la RunPod: 3 VR$ pentru imagini din «The Zero Script Club».');
  assert.equal(cost.text, 'Cost facturat la RunPod: 3 VR$ pentru imagini din «The Zero Script Club».');
  assert.ok(!cost.text.includes('prov-7f3a'));
  assert.equal(cost.kind, 'money');
  const repair = said('media.sheet_repair_finished', { status: 'RESOLVED' }, 'Foaia «The Zero Script Club» e curată: filmarea merge mai departe.');
  assert.equal(repair.text, 'Foaia «The Zero Script Club» e curată: filmarea merge mai departe.');
  const fired = said('workflow.job_fired', { workflow_type: 'DAILY_RUN', job_name: 'daily_run' }, 'Ceasul studioului a pornit rularea zilei.');
  assert.equal(fired.text, 'Ceasul studioului a pornit rularea zilei.');
  assert.equal(fired.routine, undefined);
  // a routine job's fire still folds as the routine row, whatever the backend says of it
  const routine = said('workflow.job_fired', { workflow_type: 'WATCHDOG' }, 'Ceasul studioului a pornit supraveghetorul.');
  assert.equal(routine.label, 'sarcină de rutină pornită');
  assert.equal(routine.routine, 'WATCHDOG');
  // the GPU's events are production, said by the editor who opened it, without his name twice
  const gpu = said('runpod.gpu_session_opened', { purpose: 'image', step: 'stills' }, 'Kael (Video Editor) a pornit GPU-ul RunPod pentru imagini din «The Zero Script Club» (imagini); modelul se încarcă (~10 min).', kael);
  assert.equal(gpu.kind, 'production');
  assert.equal(gpu.who, 'Kael (Video Editor)');
  assert.equal(gpu.text, 'a pornit GPU-ul RunPod pentru imagini din «The Zero Script Club» (imagini); modelul se încarcă (~10 min).');
  assert.equal(gpu.portrait, 'a-9');
  // without words the page keeps its own lines
  assert.equal(said('media.video_rendered', { provider_name: 'ffmpeg-local' }, undefined).label, 'video randat');
  assert.equal(said('media.qc_evaluated', { status: 'PASSED' }, undefined).label, 'controlul calității: trecută');
});
