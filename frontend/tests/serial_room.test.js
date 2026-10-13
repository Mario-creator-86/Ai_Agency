// THE SERIAL, SHOWN AS A WRITERS ROOM (serial_room.js).
//
// The episode used to be printed as a scene in bold and then its whole dialogue in one run,
// "Sarah: (sighs) Okay, so …": the speaker glued into the words, the direction read as if it
// were spoken. The backend now gives each beat its part, its room and its lines as
// {speaker, text, direction?}, the Director six scores beside the computed checks, and every
// episode a plan for the next one. These tests hold the page to those shapes, as the backend
// writes them (services.py write_episode, review.py review_episode, serial_stage.py), and to
// the one rule the page adds: it words the labels, never the story.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  approvalMessage,
  beatLines,
  checkRows,
  countWord,
  daysClosedNote,
  episodeHtml,
  nextPlan,
  partWord,
  planHeading,
  receivedPlan,
  roomOf,
  rubricRows,
  serialBoardHtml,
  serialStageNotes,
  journalCoverHtml,
  coverVerdict,
  dayWords,
  splitName,
  textParts,
} from '../src/serial_room.js';
import { describeEvent } from '../src/ledger.js';

const V3_BEAT = {
  beat_number: 1,
  part: 'hook',
  location: 'video_studio',
  scene: 'The render bay on floor one.',
  lines: [
    { speaker: 'Kael (Video Editor)', text: 'Ninety-seven percent. Since lunch.', direction: 'without looking up' },
    { speaker: 'Lyra (Voice Artist)', text: 'Then it is nearly done.' },
  ],
  dialogue: 'Ninety-seven percent. Since lunch.\nThen it is nearly done.',
  speakers: ['Kael (Video Editor)', 'Lyra (Voice Artist)'],
  background: ['Sarah (Director)'],
  characters: ['Kael (Video Editor)', 'Lyra (Voice Artist)'],
  event_ids: ['e1'],
};

const REVIEW = {
  verdict: 'PASS',
  story: 'A clean hook.',
  reasons: [],
  notes: '',
  scores: { hook: 4, situation: 4, turn: 5, payoff: 2, voices: 4, button: 5 },
  template_version: 'director-rubric-v1',
  approved_by_policy: false,
  checks: {
    language: { passed: true, reason: 'Titlul și replicile sunt în engleză.', lines: 10, lines_not_english: 0 },
    grounding: { passed: true, reason: 'Toate citările există.', cited: 5 },
    structure: { passed: false, reason: 'Beat-ul 3 nu are o parte.' },
    words_per_beat: { passed: true, reason: 'ok', per_beat: [14, 18, 12] },
    shiny_new_rule: { passed: true, reason: 'ok' },
  },
};

test('a v3 beat keeps each line as the backend wrote it: speaker, words and direction apart', () => {
  const lines = beatLines(V3_BEAT);
  assert.equal(lines.length, 2);
  assert.deepEqual(lines[0], { speaker: 'Kael (Video Editor)', text: 'Ninety-seven percent. Since lunch.', direction: 'without looking up' });
  assert.equal(lines[1].direction, '');
});

test('a v2 beat is read row by row, and no name is left glued into the words', () => {
  const lines = beatLines({
    dialogue: 'Sarah: (sighs) Okay, so the render failed.\nKael (Video Editor): Again.\nThe lights flicker.',
    characters: ['Sarah (Director)', 'Kael (Video Editor)'],
  });
  assert.equal(lines.length, 3);
  assert.equal(lines[0].speaker, 'Sarah (Director)', 'the short label is matched to the cast');
  assert.equal(lines[0].direction, 'sighs');
  assert.equal(lines[0].text, 'Okay, so the render failed.');
  assert.equal(lines[1].speaker, 'Kael (Video Editor)');
  assert.equal(lines[1].text, 'Again.');
  assert.equal(lines[2].speaker, null, 'a row with no label is narration');
  for (const line of lines) assert.ok(!/^\s*\w+\s*:/.test(line.text), `no "Name:" left in: ${line.text}`);
});

test('a direction inside the words is set apart, and every character stays on the page', () => {
  const text = 'Fine. (beat) It is fine. [quietly] Really.';
  const parts = textParts(text);
  assert.equal(parts.map((p) => p.text).join(''), text);
  assert.deepEqual(parts.filter((p) => p.aside).map((p) => p.text), ['(beat)', '[quietly]']);
});

test('the parts, the rooms and the names are labelled, never reworded', () => {
  assert.deepEqual(['hook', 'situation', 'turn', 'payoff', 'button'].map(partWord), ['cârlig', 'situația', 'întorsătura', 'rezolvarea', 'poanta']);
  assert.deepEqual(roomOf('video_studio'), { floor: 'Etajul 1', name: 'Randare și montaj', short: 'Randare', known: true });
  assert.equal(roomOf('the_moon').known, false, 'a room the studio does not have is shown as written');
  assert.equal(roomOf('the_moon').name, 'the_moon');
  assert.deepEqual(splitName('Sarah (Director)'), { name: 'Sarah', role: 'Director' });
  assert.deepEqual(splitName('Kael'), { name: 'Kael', role: '' });
});

test('Romanian counts agree with their numeral', () => {
  assert.equal(countWord(1, 'beat', 'beat-uri'), '1 beat');
  assert.equal(countWord(5, 'beat', 'beat-uri'), '5 beat-uri');
  assert.equal(countWord(20, 'eveniment', 'evenimente'), '20 de evenimente');
  assert.equal(countWord(101, 'eveniment', 'evenimente'), '101 evenimente');
});

test('the rubric has six rows in order, a score under 3 is low, a computed FAIL has none', () => {
  const rows = rubricRows(REVIEW);
  assert.deepEqual(rows.map((r) => r.word), ['cârlig', 'situația', 'întorsătura', 'rezolvarea', 'vocile', 'poanta']);
  assert.deepEqual(rows.filter((r) => r.low).map((r) => r.key), ['payoff']);
  assert.ok(rubricRows({ scores: {} }).every((r) => r.score === null && !r.low));
  assert.ok(rubricRows(null).every((r) => r.score === null));
});

test('the checks come in reading order, with the labels the serial asked for and their own reasons', () => {
  const rows = checkRows(REVIEW);
  assert.deepEqual(rows.map((r) => r.key), ['grounding', 'structure', 'words_per_beat', 'language', 'shiny_new_rule']);
  assert.equal(rows[1].word, 'structură (cârlig → poantă, camere din studio)');
  assert.equal(rows[1].passed, false);
  assert.equal(rows[1].reason, 'Beat-ul 3 nu are o parte.', 'the backend reason, as it came');
  assert.equal(rows[2].word, 'cuvinte pe beat (8-22 rostite)');
  assert.equal(rows[2].measure, '14 · 18 · 12');
  assert.equal(rows[3].measure, '10 din 10 replici');
  assert.equal(rows[4].word, 'shiny new rule', 'a check the page does not know keeps its own name');
});

test('tomorrow\'s plan and the plan received read the continuity the episode carries', () => {
  const continuity = {
    next_episode: {
      premise: 'Kael gets a new GPU.',
      cold_open_line: 'It arrived in a box marked FRAGILE.',
      open_question: 'Will it fit?',
      threads_to_pay_off: ['T2'],
      status: 'PLANNED',
      planned_on: '2026-09-24',
    },
    plan: { from_episode_id: 'x', from_episode_number: 2, premise: 'Aris finds the paper.', kept: false, note: 'The day had no research.' },
  };
  const plan = nextPlan(continuity);
  assert.equal(plan.statusWord, 'planificat');
  assert.deepEqual(plan.threads, ['T2']);
  assert.equal(nextPlan({}), null);
  assert.equal(nextPlan({ next_episode: { status: 'KEPT' } }).statusWord, 'păstrat');
  assert.equal(nextPlan({ next_episode: { status: 'DROPPED' } }).statusWord, 'abandonat');
  assert.equal(nextPlan({ next_episode: { status: 'UNSAID' } }).statusWord, 'nespus');
  const received = receivedPlan(continuity);
  assert.equal(received.word, 'abandonat');
  assert.equal(received.from, 2);
  assert.equal(receivedPlan({ plan: null }), null);
  assert.equal(receivedPlan({ plan: { kept: null } }).word, 'nespus');
});

test('the approval says what happens next, or why the storyboard could not be made', () => {
  assert.equal(
    approvalMessage({ status: 'APPROVED', storyboard_id: 'sb-1' }).text,
    'Episod aprobat și pregătit de filmare; rularea următoare îl filmează.',
  );
  const failed = approvalMessage({ status: 'APPROVED', storyboard_id: null, storyboard_error: 'no cast in the bible' });
  assert.equal(failed.error, true);
  assert.equal(failed.text, 'Episod aprobat; storyboardul nu s-a putut face: no cast in the bible. Rularea următoare încearcă din nou.');
  assert.equal(approvalMessage({ status: 'APPROVED' }).text, 'Episod aprobat.');
});

test('a serial stage names the day it told, what it took up, and a refusal only when there was one', () => {
  assert.deepEqual(
    serialStageNotes({ stage: 'serial_queue', artefacts: { told_date: '2026-09-23', resumed: 'owner', refused: 0 } }),
    ['Ziua povestită: 2026-09-23', 'Episod reluat: așteaptă aprobarea ta'],
  );
  assert.deepEqual(serialStageNotes({ stage: 'serial_queue', artefacts: { resumed: 'storyboard', refused: 2 } }), [
    'Episod reluat: pregătit de filmare',
    'răspunsuri refuzate ale scenaristului: 2',
  ]);
  assert.deepEqual(serialStageNotes({ stage: 'serial_next', artefacts: { told_date: '2026-09-24', approved: 1, resumed: 'review' } }), [
    'Scenariul de mâine: 2026-09-24, se filmează la rularea următoare',
    'Episod reluat: citit din nou',
  ]);
  assert.deepEqual(serialStageNotes({ stage: 'serial_next', artefacts: { told_date: '2026-09-24', written: 1, approved: 0 } }), ['Scenariul de mâine: 2026-09-24']);
  assert.deepEqual(serialStageNotes({ stage: 'serial_next', artefacts: { told_date: '2026-09-24', written: 0, approved: 0 } }), [], 'no script, no line: the reason says why');
  assert.deepEqual(serialStageNotes({ stage: 'media', artefacts: { told_date: 'x' } }), []);
});

test('the preflight line lists the days the run closed, and nothing when it closed none', () => {
  const stage = (days) => ({ stage: 'preflight', artefacts: { previous_day_log: { days_closed: days } } });
  assert.equal(daysClosedNote(stage(['2026-09-22', '2026-09-23'])), 'Zile închise acum: 2026-09-22, 2026-09-23');
  assert.equal(daysClosedNote(stage([])), '');
  assert.equal(daysClosedNote({ stage: 'preflight', artefacts: {} }), '');
  assert.equal(daysClosedNote({ stage: 'media', artefacts: { previous_day_log: { days_closed: ['x'] } } }), '');
});

test('the new stage has its name in the register as well as on the run card', () => {
  const said = describeEvent({ event_type: 'runbook.stage_started', payload: { stage: 'serial_next', index: 14, total: 14 } });
  assert.ok(JSON.stringify(said).includes('scenariul de mâine (14/14)'), JSON.stringify(said));
});

test('an episode reads as a script page, with the rubric and tomorrow beside it', () => {
  const html = episodeHtml(
    {
      id: 'ep-1',
      title: 'The <Render>',
      status: 'DRAFT',
      beats: [V3_BEAT],
      grounded_event_ids: ['e1'],
      review: REVIEW,
      continuity: {
        episode_number: 3,
        business_date: '2026-09-23',
        next_episode: { premise: 'Next.', status: 'PLANNED', planned_on: '2026-09-23', threads_to_pay_off: [] },
      },
    },
    { open: true },
  );
  assert.ok(html.includes('The &lt;Render&gt;'), 'the title is escaped, not rendered');
  assert.ok(html.includes('<span class="line-speaker">Kael <span class="line-role">(Video Editor)</span></span>'));
  assert.ok(html.includes('<span class="line-direction">(without looking up)</span>'));
  assert.ok(!html.includes('Kael (Video Editor):'), 'no speaker glued into the words');
  assert.ok(html.includes('beat-part part-hook">cârlig'));
  assert.ok(html.includes('Etajul 1 · Randare și montaj'));
  assert.ok(html.includes('în cadru, fără replici: Sarah (Director)'));
  assert.ok(html.includes('aria-label="rezolvarea: 2 din 5"'));
  assert.ok(html.includes('tone-low'));
  assert.ok(html.includes('Scenariul de mâine'));
  assert.ok(html.includes('ciorna episodului 3'));
  assert.ok(html.includes('A trecut; politica canalului lasă aprobarea la tine.'));
  assert.ok(html.includes('data-approve="true"'), 'a draft can be approved');
  assert.ok(/\sopen>/.test(html.split('\n').find((l) => l.includes('<details')) || ''), 'the first episode opens');
});

test('a computed FAIL draws no rubric and says why; an approved episode has no approve button', () => {
  const html = episodeHtml({
    id: 'ep-2',
    title: 'T',
    status: 'APPROVED',
    reviewed_by: 'owner',
    storyboard_id: 'sb',
    beats: [],
    review: { verdict: 'FAIL', scores: {}, checks: { grounding: { passed: false, reason: 'Nicio citare.' } } },
    continuity: {},
  });
  assert.ok(html.includes('Fără rubrică'));
  assert.ok(html.includes('Nicio citare.'));
  assert.ok(!html.includes('data-approve'));
  assert.ok(html.includes('pregătit de filmare'));
  assert.ok(html.includes('Aprobat de tine'));
});

test('the serial board says where canon stands, in agreement', () => {
  assert.equal(serialBoardHtml(null), '');
  const html = serialBoardHtml({ canon_episode_number: 1, threads: [{ id: 'T1', text: 'x' }], recurring: [], summaries: [] });
  assert.ok(html.includes('1 fir deschis'));
  // W12: an empty panel is folded away; the canon's count is on the cover
  assert.equal(serialBoardHtml({ canon_episode_number: 0, threads: [] }), '');
  assert.equal(serialBoardHtml({ canon_episode_number: 0, threads: [], recurring: [] }), '');
  assert.ok(serialBoardHtml({ threads: [], recurring: ['the plastic plant'] }).includes('Revin'));
});

test('the plan card is «Scenariul de mâine» only while the plan still waits for tomorrow', () => {
  assert.deepEqual(planHeading('PLANNED', 'DRAFT'), { live: true, title: 'Scenariul de mâine' });
  assert.deepEqual(planHeading('PLANNED', 'APPROVED'), { live: true, title: 'Scenariul de mâine' });
  assert.equal(planHeading('PLANNED', 'REJECTED').live, false, "a refused draft's plan is not tomorrow's");
  assert.equal(planHeading('KEPT', 'APPROVED').title, 'Planul pentru episodul următor');
  assert.equal(planHeading('DROPPED', 'APPROVED').live, false);
});


/* ------------------------------------------------------------ W12: the cover -- */

test('the cover is the newest episode as a poster: number, title, the day it tells, the verdict', () => {
  const episode = {
    id: 'e3',
    status: 'DRAFT',
    title: "The Render That Wouldn't Wait",
    beats: [{}, {}, {}, {}, {}],
    grounded_event_ids: ['a', 'b', 'c'],
    continuity: { episode_number: 3, business_date: '2026-09-23' },
    review: {
      verdict: 'PASS',
      scores: { hook: 4, situation: 4, turn: 5, payoff: 3, voices: 4, button: 5 },
      checks: { grounding: { passed: true }, privacy: { passed: true }, cast: { passed: false, reason: 'x' }, old: { passed: false, legacy: true } },
    },
  };
  const html = journalCoverHtml(episode, { canon_episode_number: 2 });
  assert.ok(html.includes('<span class="cover-n">03</span>'));
  assert.ok(html.includes('The Render That Wouldn&#39;t Wait') || html.includes("The Render That Wouldn't Wait"));
  assert.ok(html.includes('ziua povestită 23.09.2026'));
  assert.ok(html.includes('>PASS<'));
  assert.ok(html.includes('nota medie 4,2 din 5'));
  assert.ok(html.includes('2 din 3 verificări trecute'), 'a legacy check is not counted');
  assert.ok(html.includes('5 beat-uri · 3 evenimente reale citate'));
  assert.ok(html.includes('<strong>2</strong> episoade aprobate'));
  assert.ok(html.includes('href="#ep-e3"'));
  assert.ok(html.includes('verdict-pass'));
});

test('an unnumbered, unread draft says so, and no episode is a cover that says none', () => {
  const html = journalCoverHtml({ id: 'd', status: 'DRAFT', title: 'Inside The Nexus', beats: [], grounded_event_ids: [], continuity: { business_date: '2026-09-12' } }, { canon_episode_number: 0 });
  assert.ok(html.includes('<span class="cover-n is-none">—</span>'));
  assert.ok(html.includes('fără număr în serial'));
  assert.ok(html.includes('Directorul nu a citit încă episodul.'));
  assert.ok(html.includes('>—<'));
  assert.ok(html.includes('<strong>0</strong> episoade aprobate'));
  const none = journalCoverHtml(null, null);
  assert.ok(none.includes('Niciun episod încă'));
  assert.ok(!none.includes('episoade aprobate'), 'a serial not read says no count');
  assert.deepEqual(coverVerdict(null), { verdict: '—', mean: '', checks: '', read: false });
  assert.equal(coverVerdict({ verdict: 'FAIL', scores: {}, checks: {} }).mean, '', 'a computed FAIL has no scores to average');
  assert.equal(dayWords('2026-09-12'), '12.09.2026');
  assert.equal(dayWords(''), '');
});
