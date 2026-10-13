/**
 * The serial, shown as a writers room (Journal dialog and the daily-run cards).
 *
 * The serial's backend was rebuilt on 2026-09-24 (S0-S6): a beat carries its part of the
 * story (hook, situation, turn, payoff, button), the room it happens in and its lines as
 * `{speaker, text, direction?}`; the Director's review carries six 1-5 scores beside the
 * computed checks; every episode leaves a plan for the next one. The page used to print a beat
 * as its scene in bold and then the whole free dialogue in one run — "Sarah: (sighs) Okay, so
 * …" — so an episode read as a paragraph, not as a script.
 *
 * What this module decides is only how that is shown. Every word of the episode is the
 * showrunner's, in English by design, because the channels publish in English; every reason
 * a check or a stage gives is the backend's Romanian, printed as it came. The words here are
 * the labels around them. It lives outside `main.js` for the reason `day_outcome.js` gives:
 * `main.js` touches the document the moment it is imported and cannot be run by `node --test`.
 *
 * Shapes, from the backend (read, not guessed):
 *   beat       services.py write_episode: beat_number, part, location, scene, lines,
 *              dialogue (spoken text only), speakers, background, characters, event_ids.
 *              A v2 beat (before S4) has only scene, dialogue ("Name: words" rows),
 *              characters and event_ids.
 *   review     review.py review_episode: verdict, checks{name: {passed, reason, ...}},
 *              reasons, notes, story, scores{hook..button}, template_version, run_id,
 *              model_used, reviewed_at, approved_by_policy. Scores are empty on a FAIL the
 *              computed checks decided before the Director read anything.
 *   continuity services.py write_episode: episode_number, business_date, summary, threads_*,
 *              next_episode{premise, cold_open_line, open_question, threads_to_pay_off,
 *              status, planned_on, judged_in?}, plan{from_episode_number, premise, kept, note}.
 */

import { escapeHtml } from './html.js';

/** The five parts of an episode, in order (backend EPISODE_PARTS). */
export const EPISODE_PARTS = ['hook', 'situation', 'turn', 'payoff', 'button'];

/** The part of the story a beat plays, as the writers room says it. */
export const PART_WORD = {
  hook: 'cârlig',
  situation: 'situația',
  turn: 'întorsătura',
  payoff: 'rezolvarea',
  button: 'poanta',
};

/** The Director's rubric (review.py RUBRIC) and the floor under which a PASS becomes a FAIL. */
export const RUBRIC = ['hook', 'situation', 'turn', 'payoff', 'voices', 'button'];
export const RUBRIC_WORD = { ...PART_WORD, voices: 'vocile' };
export const RUBRIC_FLOOR = 3;

/**
 * The studio's rooms, by the ids the backend's office layout gives them
 * (`DEFAULT_OFFICE_LAYOUT`, the same eleven the headquarters scene draws). A beat set in a
 * room the studio does not have is shown as the writer wrote it: the structure check already
 * says it is nowhere.
 */
export const ROOMS = {
  director_suite: ['Etajul 4', 'Direcțiunea', 'Direcțiune'],
  research_lab: ['Etajul 3', 'Cercetare', 'Cercetare'],
  factcheck_room: ['Etajul 3', 'Verificarea faptelor', 'Verificare'],
  script_room: ['Etajul 2', 'Conținut', 'Conținut'],
  publish_desk: ['Etajul 2', 'Distribuție', 'Distribuție'],
  audio_booth: ['Etajul 1', 'Cabina de voce', 'Voce'],
  video_studio: ['Etajul 1', 'Randare și montaj', 'Randare'],
  server_corner: ['Parter', 'Centrul de date', 'Date'],
  lobby: ['Parter', 'Recepția', 'Recepție'],
  accounting_office: ['Parter', 'Contabilitate și trezorerie', 'Trezorerie'],
  ad_shop: ['Parter', 'Vitrina de reclame', 'Vitrina'],
};

/** The computed checks, in the order a reader asks them, with the labels the page gives. */
export const CHECK_ORDER = [
  'grounding',
  'privacy',
  'structure',
  'cast',
  'length',
  'words_per_beat',
  'concentration',
  'accessibility',
  'language',
];
export const CHECK_WORD = {
  grounding: 'ancorare (evenimente din jurnalul zilei)',
  privacy: 'confidențialitate (doar ce este public)',
  structure: 'structură (cârlig → poantă, camere din studio)',
  cast: 'distribuție (2-4 care vorbesc)',
  length: 'durată (beat-uri și secunde de dialog)',
  words_per_beat: 'cuvinte pe beat (8-22 rostite, recomandare)',
  concentration: 'evenimente răspândite (niciunul în mai mult de jumătate din beat-uri)',
  accessibility: 'primul beat se ține singur',
  language: 'engleză (titlu și replici)',
};

/** An episode's status after the noun «episod» (masculine). */
export const STATUS_WORD = { DRAFT: 'Ciornă', APPROVED: 'Aprobat', REJECTED: 'Respins' };

/** What became of a plan for the next episode (services.py _judge_the_plan). */
export const PLAN_STATUS_WORD = {
  PLANNED: 'planificat',
  KEPT: 'păstrat',
  DROPPED: 'abandonat',
  UNSAID: 'nespus',
};

/** What a run took up from an earlier one (serial_stage.py unfinished_episodes). */
export const RESUMED_WORD = {
  storyboard: 'pregătit de filmare',
  review: 'citit din nou',
  owner: 'așteaptă aprobarea ta',
};

/**
 * A count with its noun, agreeing as Romanian does: one is singular, and a numeral takes «de»
 * when its last two digits are 00 or 20 and above («92 de evenimente», «101 evenimente»).
 * The same rule as `countLabel` in main.js, which cannot be imported here.
 *
 * @param {number} count @param {string} one @param {string} many
 */
export function countWord(count, one, many) {
  const n = Number(count) || 0;
  const rest = Math.abs(n) % 100;
  if (Math.abs(n) === 1) return `1 ${one}`;
  return `${n}${Math.abs(n) >= 20 && (rest === 0 || rest >= 20) ? ' de' : ''} ${many}`;
}

/** @param {unknown} part */
export function partWord(part) {
  const key = String(part || '').trim().toLowerCase();
  return /** @type {Record<string,string>} */ (PART_WORD)[key] || key;
}

/**
 * The room a beat is set in: its floor and name, a short name for the beat board, and
 * whether the studio has it.
 *
 * @param {unknown} location
 * @returns {{floor: string, name: string, short: string, known: boolean}}
 */
export function roomOf(location) {
  const id = String(location || '').trim();
  const known = /** @type {Record<string, string[]>} */ (ROOMS)[id];
  if (known) return { floor: known[0], name: known[1], short: known[2], known: true };
  return { floor: '', name: id, short: id, known: false };
}

/**
 * A roster name split for setting: "Sarah (Director)" -> {name: "Sarah", role: "Director"}.
 * The two parts together are the name exactly as the data gives it.
 *
 * @param {unknown} display
 */
export function splitName(display) {
  const text = String(display || '').trim();
  const match = /^(.*?)\s*\(([^()]*)\)\s*$/.exec(text);
  return match && match[1] ? { name: match[1], role: match[2] } : { name: text, role: '' };
}

/** A stage direction inside spoken text: (sighs), [quietly], *laughs* (lines.py _DIRECTION). */
const DIRECTION = /\(([^()]{1,160})\)|\[([^[\]]{1,160})\]|\*([^*]{1,160})\*/g;

/** A speaker's label at the start of a v2 row: "Sarah (Director): ..." (lines.py _LABEL). */
const LABEL = /^\s*([^:\n]{1,60}?)\s*:\s*([\s\S]+)$/;

/**
 * The lines of one beat, v3 or v2, as `{speaker, text, direction}`.
 *
 * A v3 beat has them. A v2 beat is read from its free `dialogue` one row at a time, as the
 * backend's `beat_lines` reads it for the storyboard: a short label before a colon is the
 * speaker, matched to the beat's own cast by name when it can be, and a direction that opens
 * the row is taken out to sit above the words. Directions inside the words stay where the
 * writer put them; `textParts` sets them apart. A row with no label is the narrator's
 * (`speaker: null`). Nothing is reworded: every character of the dialogue is on the page.
 *
 * @param {{lines?: unknown, dialogue?: unknown, characters?: unknown}} beat
 * @returns {{speaker: string | null, text: string, direction: string}[]}
 */
export function beatLines(beat) {
  if (Array.isArray(beat.lines) && beat.lines.length) {
    return beat.lines
      .filter((line) => line && typeof line === 'object' && String(line.text || '').trim())
      .map((line) => ({
        speaker: line.speaker ? String(line.speaker) : null,
        text: String(line.text),
        direction: line.direction ? String(line.direction) : '',
      }));
  }
  const cast = Array.isArray(beat.characters) ? beat.characters.map(String) : [];
  const found = [];
  for (const raw of String(beat.dialogue || '').split(/\r?\n/)) {
    const row = raw.trim();
    if (!row) continue;
    const match = LABEL.exec(row);
    const label = match && match[1].trim().split(/\s+/).length <= 4 ? match[1].trim() : null;
    let text = label && match ? match[2].trim() : row;
    let direction = '';
    const opening = /^\(([^()]{1,160})\)\s*/.exec(text);
    if (label && opening && opening[0].length < text.length) {
      direction = opening[1].trim();
      text = text.slice(opening[0].length);
    }
    const key = label ? label.toLowerCase() : '';
    const speaker = label
      ? cast.find((name) => name.toLowerCase() === key || splitName(name).name.toLowerCase() === key) || label
      : null;
    found.push({ speaker, text, direction });
  }
  return found;
}

/**
 * Spoken words with the directions inside them set apart, in order.
 *
 * @param {string} text
 * @returns {{text: string, aside: boolean}[]}
 */
export function textParts(text) {
  const parts = [];
  let last = 0;
  for (const match of String(text).matchAll(DIRECTION)) {
    const at = match.index ?? 0;
    if (at > last) parts.push({ text: text.slice(last, at), aside: false });
    parts.push({ text: match[0], aside: true });
    last = at + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), aside: false });
  return parts;
}

/**
 * The Director's six scores as rows. A score missing from the review is `null` (a computed
 * FAIL is decided before she reads anything, so there is no rubric to draw); a score below
 * the floor is `low`.
 *
 * @param {{scores?: Record<string, number>} | null | undefined} review
 */
export function rubricRows(review) {
  const scores = (review && review.scores) || {};
  return RUBRIC.map((key) => {
    const value = scores[key];
    const score = typeof value === 'number' && Number.isFinite(value) ? value : null;
    return {
      key,
      word: /** @type {Record<string,string>} */ (RUBRIC_WORD)[key],
      score,
      low: score !== null && score < RUBRIC_FLOOR,
    };
  });
}

/**
 * What one computed check measured, in a few words. Only numbers the check itself carries;
 * a check that carries none gets no measure rather than an invented one.
 *
 * @param {string} key
 * @param {Record<string, any>} check
 */
export function checkMeasure(key, check) {
  if (!check || typeof check !== 'object') return '';
  switch (key) {
    case 'grounding':
      return typeof check.cited === 'number' ? countWord(check.cited, 'eveniment citat', 'evenimente citate') : '';
    case 'length':
      return typeof check.seconds === 'number'
        ? `${countWord(check.beats, 'beat', 'beat-uri')} · ${check.seconds} s de dialog`
        : '';
    case 'words_per_beat':
      return Array.isArray(check.per_beat) && check.per_beat.length ? check.per_beat.join(' · ') : '';
    case 'concentration':
      return typeof check.most_cited === 'number' && typeof check.beats === 'number'
        ? `cel mai citat: în ${check.most_cited} din ${check.beats}`
        : '';
    case 'cast': {
      const speakers = Array.isArray(check.speakers) ? check.speakers : null;
      return speakers ? `vorbesc ${speakers.length}` : '';
    }
    case 'language':
      return typeof check.lines === 'number' && typeof check.lines_not_english === 'number'
        ? `${check.lines - check.lines_not_english} din ${check.lines} replici`
        : '';
    default:
      return '';
  }
}

/**
 * The computed checks as rows, known ones first in `CHECK_ORDER`, any the page does not know
 * after them under their own name. `legacy` is a rule an old episode was never told, measured
 * and not held against it. `advisory` is a recommendation (words per beat, 2026-10-13):
 * measured and shown, decided by the Director, refusing nothing.
 *
 * @param {{checks?: Record<string, any>} | null | undefined} review
 */
export function checkRows(review) {
  const checks = (review && review.checks) || {};
  const keys = [...CHECK_ORDER.filter((k) => k in checks), ...Object.keys(checks).filter((k) => !CHECK_ORDER.includes(k))];
  return keys.map((key) => {
    const check = checks[key] || {};
    return {
      key,
      word: /** @type {Record<string,string>} */ (CHECK_WORD)[key] || key.replace(/_/g, ' '),
      passed: check.passed === true,
      legacy: check.legacy === true,
      advisory: check.advisory === true,
      reason: typeof check.reason === 'string' ? check.reason : '',
      measure: checkMeasure(key, check),
    };
  });
}

/**
 * «N din M trecute» over the rules alone; a recommendation the episode is outside of is
 * counted apart («· 1 recomandare de decis»), since it refuses nothing (2026-10-13).
 *
 * @param {ReturnType<typeof checkRows>} rows
 */
export function checksCount(rows) {
  const rules = rows.filter((row) => !row.advisory);
  const advised = rows.filter((row) => row.advisory && !row.passed && !row.legacy).length;
  const head = rules.length ? `${rules.filter((row) => row.passed).length} din ${rules.length} trecute` : '';
  const tail = advised ? `${countWord(advised, 'recomandare', 'recomandări')} de decis` : '';
  return [head, tail].filter(Boolean).join(' · ');
}

/**
 * The plan an episode left for the next one, or null.
 *
 * @param {Record<string, any> | null | undefined} continuity
 */
export function nextPlan(continuity) {
  const plan = continuity && continuity.next_episode;
  if (!plan || typeof plan !== 'object') return null;
  const status = String(plan.status || '').toUpperCase();
  return {
    premise: String(plan.premise || ''),
    coldOpen: String(plan.cold_open_line || ''),
    question: String(plan.open_question || ''),
    threads: Array.isArray(plan.threads_to_pay_off) ? plan.threads_to_pay_off.map(String) : [],
    status,
    statusWord: /** @type {Record<string,string>} */ (PLAN_STATUS_WORD)[status] || status.toLowerCase(),
    plannedOn: String(plan.planned_on || ''),
    judgedIn: plan.judged_in ? String(plan.judged_in) : '',
  };
}

/**
 * What the plan card is called. «Scenariul de mâine» is the plan still waiting for tomorrow: a
 * PLANNED plan left by an episode that was not refused. A plan already judged (kept, dropped,
 * unsaid), or one left by a refused draft, is history, and is called by what it was.
 *
 * @param {string} planStatus @param {string} episodeStatus
 */
export function planHeading(planStatus, episodeStatus) {
  const live = String(planStatus).toUpperCase() === 'PLANNED' && String(episodeStatus).toUpperCase() !== 'REJECTED';
  return { live, title: live ? 'Scenariul de mâine' : 'Planul pentru episodul următor' };
}

/**
 * What an episode did with the plan it was handed: «Planul primit: păstrat — <note>».
 *
 * @param {Record<string, any> | null | undefined} continuity
 */
export function receivedPlan(continuity) {
  const plan = continuity && continuity.plan;
  if (!plan || typeof plan !== 'object') return null;
  const word = plan.kept === true ? 'păstrat' : plan.kept === false ? 'abandonat' : 'nespus';
  return {
    word,
    kept: plan.kept === true ? 'kept' : plan.kept === false ? 'dropped' : 'unsaid',
    from: typeof plan.from_episode_number === 'number' ? plan.from_episode_number : null,
    premise: String(plan.premise || ''),
    note: String(plan.note || ''),
  };
}

/**
 * What the Owner's approval did, from the decide answer (router.py post_decide): the
 * storyboard is built at once from rows, no vendor called, and the next run films it; or it
 * could not be built, the approval stands, and the next run tries again.
 *
 * @param {{status?: string, storyboard_id?: string | null, storyboard_error?: string} | null | undefined} decided
 */
export function approvalMessage(decided) {
  if (decided && decided.storyboard_error) {
    return {
      text: `Episod aprobat; storyboardul nu s-a putut face: ${decided.storyboard_error}. Rularea următoare încearcă din nou.`,
      error: true,
    };
  }
  if (decided && decided.storyboard_id) {
    return { text: 'Episod aprobat și pregătit de filmare; rularea următoare îl filmează.', error: false };
  }
  return { text: 'Episod aprobat.', error: false };
}

/**
 * What the Owner's «Scrie episodul» did, from the tell answer (router.py post_tell,
 * serial_stage.py tell_day_now, 2026-10-13). Until then the button only drafted, and the
 * Director read the draft at the next run; now the press writes, reads, approves under the
 * policy and readies, and the backend says where the episode ended in its own words
 * (`words`: approved and readied, passed and waiting for him, rejected by the Director or by
 * the computed checks, written but unread). The page decides only the tone: a rejection and
 * an unread draft take the error tone so they are not missed, and a replay of the same press
 * (the same command id, answered once already) says so.
 *
 * @param {{words?: string, reason?: string, episode_status?: string | null, verdict?: string | null, replayed?: boolean} | null | undefined} result
 * @returns {{text: string, error: boolean}}
 */
export function tellOutcomeMessage(result) {
  const words = String((result && (result.words || result.reason)) || '').trim();
  if (!words) return { text: 'Studioul nu a spus ce s-a întâmplat cu episodul; reîncarcă lista.', error: true };
  const status = String((result && result.episode_status) || '');
  const verdict = String((result && result.verdict) || '');
  const error = !status || status === 'REJECTED' || (status === 'DRAFT' && verdict !== 'PASS');
  const text = result && result.replayed ? `${words} (aceeași apăsare, răspunsul de atunci)` : words;
  return { text, error };
}

/**
 * The serial's facts on a run card, under the stage's own reason (which already names the
 * episode and its date). Only what the artefacts carry, and nothing for a count of zero.
 *
 * @param {{stage?: string, artefacts?: Record<string, any>}} stage
 * @returns {string[]}
 */
export function serialStageNotes(stage) {
  const name = String(stage.stage || '');
  if (name !== 'serial_queue' && name !== 'serial_next') return [];
  const a = stage.artefacts || {};
  const notes = [];
  if (a.told_date) {
    if (name === 'serial_next') {
      // Only when a script for that day exists: a stage that wrote nothing (tomorrow's slot
      // still held by a draft he has not decided) already says so in its reason.
      if (Number(a.written) > 0 || Number(a.approved) > 0 || a.resumed) notes.push(
        `Scenariul de mâine: ${a.told_date}${Number(a.approved) > 0 ? ', se filmează la rularea următoare' : ''}`,
      );
    } else {
      notes.push(`Ziua povestită: ${a.told_date}`);
    }
  }
  const resumed = a.resumed ? /** @type {Record<string,string>} */ (RESUMED_WORD)[String(a.resumed)] : '';
  if (resumed) notes.push(`Episod reluat: ${resumed}`);
  if (Number(a.refused) > 0) notes.push(`răspunsuri refuzate ale scenaristului: ${Number(a.refused)}`);
  return notes;
}

/**
 * The dates the run closed before it started (runbook services.py _close_previous_day), on
 * the preflight line; nothing when it closed none.
 *
 * @param {{stage?: string, artefacts?: Record<string, any>}} stage
 */
export function daysClosedNote(stage) {
  if (String(stage.stage || '') !== 'preflight') return '';
  const log = (stage.artefacts || {}).previous_day_log;
  const days = log && Array.isArray(log.days_closed) ? log.days_closed.filter(Boolean) : [];
  return days.length ? `Zile închise acum: ${days.join(', ')}` : '';
}

/* ------------------------------------------------------------------------------------------
 * THE MARKUP
 * ---------------------------------------------------------------------------------------- */

const CHECK_ICON = {
  pass: '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5.5 12.5l4.2 4.2 8.8-9.4"/></svg>',
  fail: '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>',
  legacy: '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12h12"/></svg>',
  advice: '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v9M12 18.5v.5"/></svg>',
};

/** @param {string} display */
function speakerHtml(display) {
  const { name, role } = splitName(display);
  return `<span class="line-speaker">${escapeHtml(name)}${role ? ` <span class="line-role">(${escapeHtml(role)})</span>` : ''}</span>`;
}

/** @param {string} text */
function wordsHtml(text) {
  return textParts(text)
    .map((part) => (part.aside ? `<em class="line-aside">${escapeHtml(part.text)}</em>` : escapeHtml(part.text)))
    .join('');
}

/** @param {string} direction */
function directionHtml(direction) {
  const text = direction.trim();
  if (!text) return '';
  const wrapped = /^\(.*\)$/.test(text) ? text : `(${text})`;
  return `<span class="line-direction">${escapeHtml(wrapped)}</span>`;
}

/**
 * @param {string} episodeId
 * @param {Record<string, any>} beat
 * @param {number} index
 */
function beatHtml(episodeId, beat, index) {
  const number = Number(beat.beat_number) || index + 1;
  const part = String(beat.part || '').trim().toLowerCase();
  const room = roomOf(beat.location);
  const lines = beatLines(beat);
  const background = Array.isArray(beat.background) ? beat.background : [];
  const cited = Array.isArray(beat.event_ids) ? beat.event_ids.length : 0;
  const slug = [
    `<span class="beat-no">${String(number).padStart(2, '0')}</span>`,
    part ? `<span class="beat-part part-${escapeHtml(part)}">${escapeHtml(partWord(part))}</span>` : '',
    room.name
      ? `<span class="beat-room${room.known ? '' : ' is-unknown'}">${room.floor ? `${escapeHtml(room.floor)} · ` : ''}${escapeHtml(room.name)}</span>`
      : '',
  ].join('');
  const said = lines
    .map((line) =>
      line.speaker
        ? `<div class="script-line">${speakerHtml(line.speaker)}${directionHtml(line.direction)}<p class="line-text">${wordsHtml(line.text)}</p></div>`
        : `<p class="beat-action beat-narration">${wordsHtml(line.text)}</p>`,
    )
    .join('');
  const foot = [
    countWord(cited, 'eveniment citat', 'evenimente citate'),
    background.length ? `în cadru, fără replici: ${background.map(String).join(', ')}` : '',
  ].filter(Boolean);
  return `
    <section class="script-beat" id="beat-${escapeHtml(episodeId)}-${number}" tabindex="-1" aria-label="Beat ${number}${part ? `, ${escapeHtml(partWord(part))}` : ''}">
      <header class="beat-slug">${slug}</header>
      ${beat.scene ? `<p class="beat-action" lang="en">${escapeHtml(String(beat.scene))}</p>` : ''}
      <div class="beat-lines" lang="en">${said}</div>
      <footer class="beat-foot">${escapeHtml(foot.join(' · '))}</footer>
    </section>`;
}

/**
 * The beat board: one index card per beat, its part, its room and who speaks. Each is a link
 * to its beat on the page below.
 *
 * @param {string} episodeId @param {Record<string, any>[]} beats
 */
function beatBoardHtml(episodeId, beats) {
  if (!beats.length) return '';
  const cards = beats
    .map((beat, index) => {
      const number = Number(beat.beat_number) || index + 1;
      const part = String(beat.part || '').trim().toLowerCase();
      const room = roomOf(beat.location);
      const who = beatLines(beat)
        .map((line) => line.speaker)
        .filter((name, i, all) => name && all.indexOf(name) === i)
        .map((name) => splitName(name).name);
      return `<li><a class="beat-card part-${escapeHtml(part || 'none')}" href="#beat-${escapeHtml(episodeId)}-${number}">
          <span class="beat-card-head"><span class="beat-card-no">${String(number).padStart(2, '0')}</span><span class="beat-card-part">${escapeHtml(part ? partWord(part) : `beat ${number}`)}</span></span>
          ${room.short ? `<span class="beat-card-room">${escapeHtml(room.short)}</span>` : ''}
          ${who.length ? `<span class="beat-card-who">${escapeHtml(who.join(' · '))}</span>` : ''}
        </a></li>`;
    })
    .join('');
  return `<ol class="beat-board" aria-label="Structura episodului, beat cu beat">${cards}</ol>`;
}

/** @param {Record<string, any> | null | undefined} review @param {string} status */
function directorHtml(review, status) {
  if (!review) {
    return `<section class="writers-card director-card is-unread" aria-label="Citirea Directorului">
        <h4 class="writers-card-title">Citirea Directorului</h4>
        <p class="writers-empty">Directorul nu a citit încă episodul.</p>
      </section>`;
  }
  const verdict = String(review.verdict || '').toUpperCase();
  const rows = rubricRows(review);
  const scored = rows.some((row) => row.score !== null);
  const rubric = scored
    ? `<ul class="rubric" aria-label="Rubrica Directorului, note de la 1 la 5">${rows
        .map((row) => {
          const filled = row.score === null ? 0 : Math.max(0, Math.min(5, Math.round(row.score)));
          const tone = row.score === null ? 'none' : row.low ? 'low' : row.score >= 4 ? 'high' : 'mid';
          const cells = Array.from({ length: 5 }, (_, i) => `<i class="${i < filled ? 'on' : ''}"></i>`).join('');
          return `<li class="rubric-row tone-${tone}">
              <span class="rubric-word">${escapeHtml(row.word)}</span>
              <span class="rubric-bar" role="img" aria-label="${escapeHtml(row.word)}: ${row.score === null ? 'fără notă' : `${row.score} din 5`}">${cells}</span>
              <span class="rubric-score">${row.score === null ? '—' : `${row.score}/5`}</span>
            </li>`;
        })
        .join('')}</ul>`
    : review.model_used === true
      ? `<p class="writers-empty">Fără rubrică: Directorul a dat verdictul fără note pe părți.</p>`
      : `<p class="writers-empty">Fără rubrică: verificările calculate au oprit episodul înainte ca Directorul să-l citească.</p>`;
  const checks = checkRows(review);
  const checkList = checks.length
    ? `<div class="checks-head"><span>Verificări calculate</span><span class="checks-count">${escapeHtml(checksCount(checks))}</span></div>
       <ul class="check-list">${checks
         .map((row) => {
           const state = row.legacy ? 'legacy' : row.passed ? 'pass' : row.advisory ? 'advice' : 'fail';
           const said = state === 'pass' ? 'trecută' : state === 'fail' ? 'picată' : state === 'advice' ? 'în afara recomandării, decide Directorul' : 'neaplicată episodului vechi';
           return `<li class="check-row is-${state}">
               <span class="check-mark">${CHECK_ICON[state]}<span class="serial-sr">${said}</span></span>
               <span class="check-word">${escapeHtml(row.word)}</span>
               ${row.measure ? `<span class="check-measure">${escapeHtml(row.measure)}</span>` : ''}
               ${!row.passed && row.reason ? `<span class="check-reason">${escapeHtml(row.reason)}</span>` : ''}
             </li>`;
         })
         .join('')}</ul>`
    : '';
  const reasons = Array.isArray(review.reasons) ? review.reasons.filter(Boolean) : [];
  const waiting =
    verdict === 'PASS' && status === 'DRAFT' && review.approved_by_policy === false
      ? '<p class="director-policy">A trecut; politica canalului lasă aprobarea la tine.</p>'
      : '';
  return `<section class="writers-card director-card verdict-${escapeHtml(verdict.toLowerCase() || 'none')}" aria-label="Citirea Directorului">
      <div class="writers-card-head">
        <h4 class="writers-card-title">Citirea Directorului</h4>
        ${verdict ? `<span class="verdict-chip">${escapeHtml(verdict)}</span>` : ''}
      </div>
      ${review.story ? `<p class="director-story" lang="en">${escapeHtml(String(review.story))}</p>` : ''}
      ${waiting}
      ${rubric}
      ${reasons.length ? `<ul class="director-reasons">${reasons.map((r) => `<li>${escapeHtml(String(r))}</li>`).join('')}</ul>` : ''}
      ${verdict === 'FAIL' && review.notes ? `<p class="director-notes"><span class="writers-label">Pentru rescriere</span> ${escapeHtml(String(review.notes))}</p>` : ''}
      ${checkList}
    </section>`;
}

/**
 * @param {Record<string, any> | null | undefined} continuity
 * @param {Map<string, string>} titles
 */
function tomorrowHtml(continuity, titles, status) {
  const plan = nextPlan(continuity);
  if (!plan) return '';
  const judged = plan.judgedIn && titles.get(plan.judgedIn);
  const heading = planHeading(plan.status, status);
  const field = (/** @type {string} */ label, /** @type {string} */ value, cls = '') =>
    value ? `<div class="plan-field${cls}"><dt>${label}</dt><dd lang="en">${escapeHtml(value)}</dd></div>` : '';
  return `<section class="writers-card tomorrow-card plan-${escapeHtml(plan.status.toLowerCase() || 'none')}${heading.live ? ' is-live' : ''}" aria-label="${heading.title}">
      <div class="writers-card-head">
        <h4 class="writers-card-title">${heading.title}</h4>
        <span class="plan-chip">${escapeHtml(plan.statusWord)}</span>
      </div>
      <p class="writers-sub">${heading.live ? 'Planul pentru episodul următor' : 'Plan'}${plan.plannedOn ? `, scris pe ${escapeHtml(plan.plannedOn)}` : ''}${judged ? `; judecat în „${escapeHtml(judged)}”` : ''}</p>
      <dl class="plan-fields">
        ${field('premisa', plan.premise)}
        ${plan.coldOpen ? `<div class="plan-field plan-cold-open"><dt>replica de deschidere</dt><dd lang="en"><span class="cold-open-line">${escapeHtml(plan.coldOpen)}</span></dd></div>` : ''}
        ${field('întrebarea deschisă', plan.question, ' plan-question')}
        ${
          plan.threads.length
            ? `<div class="plan-field"><dt>fire de plătit</dt><dd class="thread-chips">${plan.threads.map((t) => `<span class="thread-chip">${escapeHtml(t)}</span>`).join('')}</dd></div>`
            : ''
        }
      </dl>
    </section>`;
}

/** @param {Record<string, any> | null | undefined} continuity */
function receivedHtml(continuity) {
  const plan = receivedPlan(continuity);
  if (!plan) return '';
  return `<section class="writers-card received-card is-${plan.kept}" aria-label="Planul primit">
      <p><span class="writers-label">Planul primit${plan.from !== null ? ` de la episodul ${plan.from}` : ''}:</span> <strong class="received-word">${escapeHtml(plan.word)}</strong>${plan.note ? ` — <span lang="en">${escapeHtml(plan.note)}</span>` : ''}</p>
      ${plan.premise ? `<p class="received-premise" lang="en">${escapeHtml(plan.premise)}</p>` : ''}
    </section>`;
}

/**
 * One episode as a script page, with the Director's reading and tomorrow's plan beside it.
 *
 * @param {Record<string, any>} episode
 * @param {{open?: boolean, titles?: Map<string, string>}} [context]
 */
export function episodeHtml(episode, context = {}) {
  const titles = context.titles || new Map();
  const id = String(episode.id || '');
  const status = String(episode.status || '').toUpperCase();
  const continuity = episode.continuity || {};
  const beats = Array.isArray(episode.beats) ? episode.beats : [];
  const number = typeof continuity.episode_number === 'number' ? continuity.episode_number : null;
  const date = continuity.business_date ? String(continuity.business_date) : '';
  const statusWord = /** @type {Record<string,string>} */ (STATUS_WORD)[status] || status;
  const by =
    episode.reviewed_by === 'owner'
      ? 'de tine'
      : episode.reviewed_by === 'director'
        ? 'de Director'
        : episode.reviewed_by === 'checks'
          ? 'de verificările calculate'
          : '';
  const kicker = [
    number !== null ? (status === 'APPROVED' ? `Episodul ${number}` : `ciorna episodului ${number}`) : 'Episod fără număr în serial',
    date ? `ziua ${dayWords(date)}` : '',
  ].filter(Boolean);
  const rewrite = episode.rewrite_of_id ? titles.get(String(episode.rewrite_of_id)) : '';
  const meta = [
    countWord(beats.length, 'beat', 'beat-uri'),
    countWord((episode.grounded_event_ids || []).length, 'eveniment real citat', 'evenimente reale citate'),
    rewrite ? `rescrie „${rewrite}”` : '',
  ].filter(Boolean);
  const verdict = episode.review ? String(episode.review.verdict || '').toUpperCase() : '';
  const threadsOpened = Array.isArray(continuity.threads_opened) ? continuity.threads_opened : [];
  const threadsClosed = Array.isArray(continuity.threads_closed) ? continuity.threads_closed : [];
  const threadsContinued = Array.isArray(continuity.threads_continued) ? continuity.threads_continued : [];
  const threadLine = [
    threadsContinued.length ? `continuă ${threadsContinued.join(', ')}` : '',
    threadsClosed.length ? `închide ${threadsClosed.join(', ')}` : '',
  ].filter(Boolean);
  const approveNote =
    number !== null
      ? `La aprobare, episodul primește numărul ${number} în serial și storyboardul; rularea următoare îl filmează.`
      : 'La aprobare, episodul primește storyboardul; rularea următoare îl filmează.';
  return `
  <details class="script-episode status-${escapeHtml(status.toLowerCase())}" id="ep-${escapeHtml(id)}" data-id="${escapeHtml(id)}"${context.open ? ' data-door-steps open' : ''}>
    <summary class="episode-slate">
      <span class="slate-number" aria-hidden="true"><span class="slate-ep">EP.</span>${number !== null ? String(number).padStart(2, '0') : '—'}</span>
      <span class="slate-kicker">${escapeHtml(kicker.join(' · '))}</span>
      <h3 class="slate-title" lang="en">${escapeHtml(String(episode.title || ''))}</h3>
      <span class="slate-meta">${escapeHtml(meta.join(' · '))}</span>
      <span class="slate-badges">
        <span class="episode-state state-${escapeHtml(status.toLowerCase())}">${escapeHtml(statusWord)}${by && status !== 'DRAFT' ? ` ${by}` : ''}</span>
        ${verdict ? `<span class="verdict-chip v-${escapeHtml(verdict.toLowerCase())}" title="Verdictul Directorului">${escapeHtml(verdict)}</span>` : ''}
        ${episode.storyboard_id ? '<span class="film-chip">pregătit de filmare</span>' : ''}
      </span>
    </summary>
    <div class="episode-room" data-door-steps>
      <div class="episode-script">
        ${beatBoardHtml(id, beats)}
        <article class="script-page" aria-label="Scenariul episodului">
          ${beats.map((beat, index) => beatHtml(id, beat, index)).join('')}
        </article>
        ${
          continuity.summary || threadLine.length || threadsOpened.length
            ? `<div class="episode-canon">
                ${continuity.summary ? `<p><span class="writers-label">Rezumat pentru episodul următor</span> <span lang="en">${escapeHtml(String(continuity.summary))}</span></p>` : ''}
                ${threadLine.length ? `<p><span class="writers-label">Fire</span> ${escapeHtml(threadLine.join(' · '))}</p>` : ''}
                ${threadsOpened.length ? `<p><span class="writers-label">Fire noi</span> <span lang="en">${threadsOpened.map((t) => escapeHtml(String(t))).join(' · ')}</span></p>` : ''}
              </div>`
            : ''
        }
      </div>
      <aside class="episode-notes" aria-label="Citirea și planul episodului">
        ${directorHtml(episode.review, status)}
        ${tomorrowHtml(continuity, titles, status)}
        ${receivedHtml(continuity)}
      </aside>
    </div>
    ${episode.notes ? `<p class="claim-notes episode-owner-notes">${escapeHtml(String(episode.notes))}</p>` : ''}
    <div class="episode-actions">
      <button class="quiet btn-check-grounding" data-id="${escapeHtml(id)}">Verifică ancorarea</button>
      ${
        status === 'DRAFT'
          ? `<input class="wf-notes" aria-label="Motivul respingerii" placeholder="Motiv (obligatoriu la respingere)" maxlength="2000" />
             <button class="quiet btn-decide-episode" data-id="${escapeHtml(id)}" data-approve="false">Respinge</button>
             <button class="secondary btn-decide-episode" data-id="${escapeHtml(id)}" data-approve="true" aria-describedby="approve-note-${escapeHtml(id)}">Aprobă pentru filmare</button>
             <p class="approve-note" id="approve-note-${escapeHtml(id)}">${escapeHtml(approveNote)}</p>`
          : ''
      }
    </div>
  </details>`;
}

/**
 * The serial's memory above the episodes: where canon stands and the threads it carries.
 *
 * @param {Record<string, any> | null | undefined} continuity
 */
export function serialBoardHtml(continuity) {
  if (!continuity) return '';
  const threads = Array.isArray(continuity.threads) ? continuity.threads : [];
  const recurring = Array.isArray(continuity.recurring) ? continuity.recurring : [];
  // An empty panel is folded away (W12): «NICIUN FIR DESCHIS» over nothing was a box with
  // nothing in it. The canon's count is on the Journal's cover (journalCoverHtml).
  if (!threads.length && !recurring.length) return '';
  return `<div class="serial-board">
      <div class="serial-threads">
        <span class="writers-label">${threads.length ? countWord(threads.length, 'fir deschis', 'fire deschise') : 'Niciun fir deschis'}</span>
        ${threads.length ? `<ul class="serial-thread-list">${threads.map((t) => `<li><span class="thread-chip">${escapeHtml(String(t.id || ''))}</span> <span lang="en">${escapeHtml(String(t.text || ''))}</span></li>`).join('')}</ul>` : ''}
        ${recurring.length ? `<p class="serial-recurring"><span class="writers-label">Revin</span> <span lang="en">${recurring.map((r) => escapeHtml(String(r))).join(' · ')}</span></p>` : ''}
      </div>
    </div>`;
}

/**
 * A business date as the page writes a day: «2026-09-12» -> «12.09.2026». Anything else as it came.
 * @param {unknown} date
 */
export function dayWords(date) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(date || ''));
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(date || '');
}

/**
 * The Director's reading in three figures for the cover: the verdict as she gave it, the mean
 * of her six scores (one decimal, Romanian comma) and how many computed rules passed (a
 * recommendation is not counted: it refuses nothing). Only what the review carries: no review
 * is no verdict, and a FAIL the computed rules gave without her reading (`model_used` false)
 * is `computed`: the cover signs it by the checks, not by her (2026-10-13).
 * @param {Record<string, any> | null | undefined} review
 * @returns {{verdict: string, mean: string, checks: string, read: boolean, computed: boolean}}
 */
export function coverVerdict(review) {
  if (!review) return { verdict: '—', mean: '', checks: '', read: false, computed: false };
  const verdict = String(review.verdict || '').toUpperCase() || '—';
  const scores = rubricRows(review).map((row) => row.score).filter((v) => v !== null);
  const mean = scores.length
    ? `nota medie ${(scores.reduce((a, b) => a + Number(b), 0) / scores.length).toFixed(1).replace('.', ',')} din 5`
    : '';
  const rows = checkRows(review).filter((row) => !row.legacy && !row.advisory);
  const checks = rows.length ? `${rows.filter((row) => row.passed).length} din ${countWord(rows.length, 'verificare trecută', 'verificări trecute')}` : '';
  const computed = verdict === 'FAIL' && review.model_used === false;
  return { verdict, mean, checks, read: true, computed };
}

/**
 * THE JOURNAL'S COVER (W12): the newest episode as a poster — its number in the display face,
 * its title, the day it tells, and the Director's verdict — with the serial's canon count under
 * it. The episode's words are the showrunner's (English, lang="en"); the labels are the page's.
 * A value the record does not hold is «—».
 *
 * @param {Record<string, any> | null | undefined} episode the newest episode
 * @param {Record<string, any> | null | undefined} continuity the serial's memory (/story/continuity)
 */
export function journalCoverHtml(episode, continuity) {
  const canon = continuity ? Number(continuity.canon_episode_number) || 0 : null;
  const canonLine = canon === null
    ? ''
    : `<span class="cover-canon"><span class="writers-label">În serial</span> <strong>${canon}</strong> ${canon === 1 ? 'episod aprobat' : 'episoade aprobate'}</span>`;
  if (!episode) {
    return `<section class="journal-cover is-empty" aria-label="Coperta jurnalului">
        <div class="cover-clapper" aria-hidden="true"></div>
        <div class="cover-number"><span class="cover-ep">EPISODUL</span><span class="cover-n is-none">—</span></div>
        <div class="cover-body">
          <p class="cover-kicker">OFFICE SERIAL</p>
          <h3 class="cover-title">Niciun episod încă</h3>
          <p class="cover-meta">Episodul se scrie după ce ziua se închide.</p>
          <div class="cover-foot">${canonLine}</div>
        </div>
      </section>`;
  }
  const id = String(episode.id || '');
  const status = String(episode.status || '').toUpperCase();
  const c = episode.continuity || {};
  const number = typeof c.episode_number === 'number' ? c.episode_number : null;
  const day = dayWords(c.business_date);
  const statusWord = /** @type {Record<string,string>} */ (STATUS_WORD)[status] || status;
  const beats = Array.isArray(episode.beats) ? episode.beats.length : 0;
  const cited = (episode.grounded_event_ids || []).length;
  const v = coverVerdict(episode.review);
  const tone = v.verdict === 'PASS' ? 'pass' : v.verdict === 'FAIL' ? 'fail' : 'none';
  return `<section class="journal-cover status-${escapeHtml(status.toLowerCase())} verdict-${tone}" aria-label="Coperta jurnalului: cel mai nou episod">
      <div class="cover-clapper" aria-hidden="true"></div>
      <div class="cover-number">
        <span class="cover-ep">EPISODUL</span>
        <span class="cover-n${number === null ? ' is-none' : ''}">${number !== null ? String(number).padStart(2, '0') : '—'}</span>
        ${number === null ? '<span class="cover-n-note">fără număr în serial</span>' : ''}
      </div>
      <div class="cover-body">
        <p class="cover-kicker">OFFICE SERIAL · <span class="cover-state state-${escapeHtml(status.toLowerCase())}">${escapeHtml(statusWord)}</span>${day ? ` · ziua povestită ${escapeHtml(day)}` : ''}</p>
        <h3 class="cover-title" lang="en">${escapeHtml(String(episode.title || '—'))}</h3>
        <p class="cover-meta">${escapeHtml([countWord(beats, 'beat', 'beat-uri'), countWord(cited, 'eveniment real citat', 'evenimente reale citate')].join(' · '))}</p>
        <div class="cover-foot">
          <a class="cover-read" href="#ep-${escapeHtml(id)}">Citește scenariul</a>
          ${canonLine}
        </div>
      </div>
      <div class="cover-verdict tone-${tone}${v.computed ? ' is-computed' : ''}">
        <span class="writers-label">${v.computed ? 'Verificările calculate' : 'Verdictul Directorului'}</span>
        <strong class="cover-verdict-word">${escapeHtml(v.computed ? 'RESPINS' : v.verdict)}</strong>
        ${v.read ? [v.computed ? 'Directorul nu a citit episodul.' : v.mean, v.checks].filter(Boolean).map((line) => `<span class="cover-verdict-line">${escapeHtml(line)}</span>`).join('') : '<span class="cover-verdict-line">Directorul nu a citit încă episodul.</span>'}
      </div>
    </section>`;
}
