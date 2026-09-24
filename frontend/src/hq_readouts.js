/**
 * THE FACES MADE LEGIBLE (W10).
 *
 * At fit zoom (1.15 at 1920, 0.78 at 1280) the building's bound faces — the Treasury ticker, the
 * cork board, the tokens plate, the radar — are 30-45 screen pixels wide: true, and unreadable.
 * Each face is now a place the pointer and the keyboard can stand on. Standing on one lays a
 * glass readout beside it with the face's own words, larger, and one line of what the face is:
 *
 *   «TREZORERIE · S2» / «50.000 VR$ cheltuibili» / «azi 0 / 15 USD» / «Soldul cheltuibil …»
 *
 * Everything here is value -> words, from the same facts store the faces are drawn from
 * (hq_screens.js). Nothing is fetched, nothing is invented: a value the page does not hold is
 * «—». The surfaces' rectangles are the faces' own (hq_screens.js WALL, NOTES, the manifest's
 * screens), so what the pointer finds is exactly what is drawn.
 *
 * Also here, because they are the same kind of thing:
 *   - the façade sign's words for a building with no run under way: the next scheduled run from
 *     /scheduler/jobs, or that the schedule (or autonomy) is stopped; never a countdown;
 *   - each employee's last real task, from the register (the ledger's own events), with how long
 *     ago it was: «ultima sarcină: căutarea surselor · acum 12 zile».
 */

import {
  WALL, NOTES, paneMode, renderBayFace, treasuryFace, runSignFace, factCheckFace, writersFace, publishFace, tokensFace,
  listWords, NOT_READ,
} from './hq_screens.js';
import { runtimeLabel, taskLabel } from './ledger.js';
import { nextRunWords } from './side_readout.js';
import { amount } from './numbers.js';

/* ------------------------------------------------------------------------------------------
 * THE SURFACES
 * ---------------------------------------------------------------------------------------- */

/** The union of rectangles, in world px. @param {number[][]} rects @returns {[number, number, number, number]} */
export function unionRect(rects) {
  const x0 = Math.min(...rects.map((r) => r[0]));
  const y0 = Math.min(...rects.map((r) => r[1]));
  const x1 = Math.max(...rects.map((r) => r[0] + r[2]));
  const y1 = Math.max(...rects.map((r) => r[1] + r[3]));
  return [x0, y0, x1 - x0, y1 - y0];
}

/**
 * The bound walls, in the order the keyboard reaches them after the employees: the façade sign,
 * then the floors from the top down, each left to right. `room` is the dialog a click or Enter
 * opens (the masthead menu's own buttons), `name` how the readout names the face.
 * `prefer` is the side its card takes first (placeReadout).
 * @type {Array<{id: string, name: string, room: string, rect?: number[], screen?: string, prefer?: 'right'|'left'|'above'|'below'}>}
 */
export const SURFACES = [
  // The sign's card stands under it: beside it, it lay over the AMN-AI lettering (W12).
  { id: 'run_sign', name: 'FAȚADA · RULAREA ZILEI', room: 'open-runbook-btn', rect: WALL.run_sign, prefer: 'below' },
  { id: 'research_board', name: 'CERCETARE · L3', room: 'open-research-btn', rect: unionRect(NOTES) },
  { id: 'factcheck_board', name: 'VERIFICAREA FAPTELOR · L3', room: 'open-research-btn', rect: WALL.factcheck_board },
  { id: 'writers_screen', name: 'OFFICE SERIAL · L2', room: 'open-story-btn', rect: WALL.writers_screen },
  { id: 'publish_radar', name: 'DISTRIBUȚIE · L2', room: 'open-publishing-btn', screen: 'publish_radar' },
  { id: 'render_bay', name: 'RANDARE · L1', room: 'open-media-btn', screen: 'render_display' },
  { id: 'infra_plate', name: 'SERVERE · S1', room: 'open-treasury-btn', rect: WALL.infra_plate },
  { id: 'treasury_board', name: 'TREZORERIE · S2', room: 'open-treasury-btn', rect: WALL.treasury_board },
];

/** What a click or Enter on a surface opens, in words, for the readout's last line. */
export const ROOM_WORD = {
  'open-runbook-btn': 'Rularea zilei',
  'open-research-btn': 'Cercetarea',
  'open-story-btn': 'Jurnalul',
  'open-publishing-btn': 'Distribuția',
  'open-media-btn': 'Producția media',
  'open-treasury-btn': 'Trezoreria',
};

/**
 * The desk as a place the pointer can stand on (W12): the monitor, the chair and the figure at
 * it, and the desk itself, not the monitor alone. At fit zoom the monitor was 9-13 screen px;
 * this is 48x54 world px, 38-55 screen px at 1280-2560. The figure's own box (hq_world.js
 * drawAgents: 32x46 above the seat) and the monitor are inside it.
 * @param {{x: number, y: number}} seat @param {number[]} monitor [x, y, w, h] world px
 * @returns {[number, number, number, number]}
 */
export function deskRegion(seat, monitor) {
  const [mx, my, mw] = monitor;
  const x0 = Math.min(seat.x - DESK_HALF_W, mx - 4);
  const x1 = Math.max(seat.x + DESK_HALF_W, mx + mw + 4);
  const y0 = Math.min(seat.y - 46, my - 4);
  const y1 = seat.y + 8;
  return [x0, y0, x1 - x0, y1 - y0];
}

/** Half the desk region's width, in world px: the desk's top reaches ±24 of the seat. */
export const DESK_HALF_W = 24;

/**
 * Every surface with its rectangle in world px: the walls, and every occupied desk — the
 * monitor, the chair and the figure at it (deskRegion; the keyboard reaches its employee
 * instead).
 * @param {any} manifest the plates' manifest
 * @param {any[]} agents the employees, each with a desk_id
 * @returns {Array<{id: string, rect: number[], agent: any, room: string|null, desk: boolean}>}
 */
export function surfaceRects(manifest, agents) {
  const screens = (manifest && manifest.screens) || {};
  /** @type {Array<{id: string, rect: number[], agent: any, room: string|null, desk: boolean}>} */
  const out = [];
  for (const s of SURFACES) {
    const rect = s.rect || (screens[s.screen || ''] && screens[s.screen || ''].rect);
    if (rect) out.push({ id: s.id, rect: [...rect], agent: null, room: s.room, desk: false });
  }
  for (const [name, screen] of Object.entries(screens)) {
    if (!/^desk_.+_monitor$/.test(name) || !screen || !screen.desk) continue;
    const agent = (agents || []).find((a) => a && a.desk_id === screen.desk);
    const seat = manifest && manifest.seats ? manifest.seats[screen.desk] : null;
    const rect = seat ? deskRegion(seat, screen.rect) : [...screen.rect];
    if (agent) out.push({ id: `desk:${screen.desk}`, rect, agent, room: null, desk: true });
  }
  return out;
}

/**
 * The hit under a world point: the smallest box that holds it, so a desk's monitor is found in
 * front of the employee sitting behind it, and an employee in front of the wall behind them.
 * @template {{x0: number, y0: number, x1: number, y1: number}} H
 * @param {H[]} hits @param {number} x @param {number} y
 * @returns {H|null}
 */
export function hitAt(hits, x, y) {
  let best = null;
  let area = Infinity;
  for (const h of hits || []) {
    if (x < h.x0 || x > h.x1 || y < h.y0 || y > h.y1) continue;
    const a = (h.x1 - h.x0) * (h.y1 - h.y0);
    if (a < area) {
      best = h;
      area = a;
    }
  }
  return best;
}

/**
 * What the pointer stands on (W12): the smallest box under it, except that an employee's figure
 * is part of their desk — the pointer on the figure stands on the desk, whose card says who sits
 * there and what they last did. A figure with no desk region is itself.
 * @template {{x0: number, y0: number, x1: number, y1: number, agent?: any, desk?: boolean, surface?: string}} H
 * @param {H[]} hits @param {number} x @param {number} y
 * @returns {H|null}
 */
export function pointerHit(hits, x, y) {
  const hit = hitAt(hits, x, y);
  if (!hit || hit.surface || !hit.agent) return hit;
  const desk = (hits || []).find((h) => h.desk && h.agent === hit.agent);
  return desk || hit;
}

/* ------------------------------------------------------------------------------------------
 * WORDS
 * ---------------------------------------------------------------------------------------- */

/**
 * «1 verdict respins», «11 verdicte respinse», «20 de verdicte respinse».
 * @param {number} n @param {string} one @param {string} many
 */
export function counted(n, one, many) {
  if (n === 1) return `1 ${one}`;
  const tail = n % 100;
  return `${amount(String(n))}${n >= 20 && (tail === 0 || tail >= 20) ? ' de' : ''} ${many}`;
}

/**
 * How long ago, as the register would say it: «chiar acum», «acum 5 minute», «acum o oră»,
 * «acum 20 de ore», «acum 3 zile». Under two days in hours, as the register's quiet line does.
 * @param {number} ms how long ago
 */
export function agoWords(ms) {
  if (!Number.isFinite(ms)) return '';
  const minutes = Math.floor(Math.max(0, ms) / 60000);
  if (minutes < 1) return 'chiar acum';
  const phrase = (/** @type {number} */ n, /** @type {string} */ one, /** @type {string} */ many) => {
    if (n === 1) return `acum ${one}`;
    const tail = n % 100;
    return `acum ${n}${n >= 20 && (tail === 0 || tail >= 20) ? ' de' : ''} ${many}`;
  };
  if (minutes < 60) return phrase(minutes, 'un minut', 'minute');
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return phrase(hours, 'o oră', 'ore');
  return phrase(Math.floor(hours / 24), 'o zi', 'zile');
}

const WORKING = new Set(['WORKING', 'EXECUTING', 'RUNNING', 'THINKING', 'PLANNING', 'REVIEWING']);

/**
 * Each employee's newest real task in the register: the newest run that ended
 * (agent.run_completed, payload.agent_id) or the newest task they were seen starting
 * (agent.state_changed to work, with its task_type). Nothing older than the register holds.
 * @param {any[]} events the register, newest first
 * @returns {{tasks: Record<string, {task: string, at: number, status: string|null}>, key: string}}
 */
export function lastTasks(events) {
  /** @type {Record<string, {task: string, at: number, status: string|null}>} */
  const tasks = {};
  for (const event of Array.isArray(events) ? events : []) {
    if (!event) continue;
    const payload = event.payload || {};
    let id = null;
    let status = null;
    if (event.event_type === 'agent.run_completed' && payload.agent_id && payload.task_type) {
      id = String(payload.agent_id);
      status = payload.status ? String(payload.status) : null;
    } else if (event.event_type === 'agent.state_changed' && payload.task_type && WORKING.has(String(payload.runtime_state || '').toUpperCase())) {
      id = String(event.aggregate_id || '');
    }
    if (!id || tasks[id]) continue;
    const at = Date.parse(String(event.timestamp || ''));
    if (!Number.isFinite(at)) continue;
    tasks[id] = { task: taskLabel(String(payload.task_type)), at, status };
  }
  return { tasks, key: taskKey(tasks) };
}

/**
 * Each employee's last task from the studio's own records (W12): the snapshot's `last_tasks`,
 * the newest run of each employee, started or finished (backend app.services
 * last_task_per_agent). The register only holds the events the page replayed, so without this
 * six of the Owner's eight name tags said «—».
 * @param {Record<string, {task_type?: string, status?: string, started_at?: string, finished_at?: string|null}>|null|undefined} record
 * @returns {{tasks: Record<string, {task: string, at: number, status: string|null}>, key: string}}
 */
export function tasksFromRecord(record) {
  /** @type {Record<string, {task: string, at: number, status: string|null}>} */
  const tasks = {};
  for (const [id, run] of Object.entries(record && typeof record === 'object' ? record : {})) {
    if (!run || !run.task_type) continue;
    const at = Date.parse(String(run.finished_at || run.started_at || ''));
    if (!Number.isFinite(at)) continue;
    tasks[id] = { task: taskLabel(String(run.task_type)), at, status: run.status ? String(run.status) : null };
  }
  return { tasks, key: taskKey(tasks) };
}

/**
 * The newer of two readings of each employee's last task: the register's (live events) and the
 * record's (the snapshot). A live event is newer than the snapshot it arrived after, and the
 * snapshot remembers what the register never replayed.
 * @param {{tasks: Record<string, any>}} a @param {{tasks: Record<string, any>}} b
 */
export function newerTasks(a, b) {
  /** @type {Record<string, {task: string, at: number, status: string|null}>} */
  const tasks = { ...((a && a.tasks) || {}) };
  for (const [id, task] of Object.entries((b && b.tasks) || {})) {
    if (!tasks[id] || task.at > tasks[id].at) tasks[id] = task;
  }
  return { tasks, key: taskKey(tasks) };
}

/** @param {Record<string, {task: string, at: number}>} tasks */
function taskKey(tasks) {
  return Object.keys(tasks).sort().map((id) => `${id}|${tasks[id].task}|${tasks[id].at}`).join('#');
}

/**
 * The faint line under an employee's name: their last real task, or a dash when the register
 * holds none. @param {{task: string, at: number}|null|undefined} last @param {number} now
 */
export function lastTaskLine(last, now) {
  if (!last) return 'ultima sarcină: —';
  return `ultima sarcină: ${last.task} · ${agoWords(now - last.at)}`;
}

/**
 * What the façade sign says of the next run while none is under way: the scheduler's own time
 * for the daily job, only while that job is active and autonomy is on; otherwise that the
 * schedule (or autonomy) is stopped. Never a countdown, never a time the scheduler did not give.
 * @param {any[]|null|undefined} jobs /scheduler/jobs
 * @param {{stopped?: boolean|null, timeZone?: string}} [context]
 * @returns {string} '' when the page has not read the schedule
 */
export function nextRunSign(jobs, context = {}) {
  if (!Array.isArray(jobs)) return '';
  const words = nextRunWords(jobs, context);
  if (words.tone !== 'ok') return words.value === '—' ? '' : words.value;
  return `următoarea rulare ${words.value.replace(/,\s(?=\d{2}\.\d{2})/, ' ')}`;
}

/* ------------------------------------------------------------------------------------------
 * THE READOUT OF ONE SURFACE
 * ---------------------------------------------------------------------------------------- */

/**
 * @typedef {{id: string, eyebrow: string, value: string, line: string, context: string, action: string,
 *            tone: 'ok'|'warn'|'alert'|'quiet', poster: boolean, key: string}} Readout
 */

/** @param {Omit<Readout, 'key'>} r @returns {Readout} */
function keyed(r) {
  return { ...r, key: [r.id, r.eyebrow, r.value, r.line, r.context, r.action, r.tone, r.poster].join('|') };
}

/** @param {string} room */
function openWords(room) {
  const word = /** @type {Record<string, string>} */ (ROOM_WORD)[room];
  return word ? `Clic sau Enter: deschide ${word}.` : '';
}

/** What the idle façade's card offers when a finished day is on record (W13). */
export const REPLAY_ACTION = 'Clic sau Enter: Vezi ultima rulare încheiată.';

/**
 * Whether the façade sign offers «Reluarea zilei»: a finished run is on record (facts.replayOffer)
 * and none is under way or open today (W13).
 * @param {any} facts @param {{underWay: boolean, open: boolean}} face
 */
export function replayOffered(facts, face) {
  return Boolean(facts && facts.replayOffer) && !face.underWay && !face.open;
}

/** @param {any[]} agents @param {string} desk */
const atDesk = (agents, desk) => (agents || []).find((a) => a && a.desk_id === desk) || null;

/**
 * The readout for a surface, from the facts the faces are drawn from.
 * @param {string} id a SURFACES id, or 'desk:<desk_id>'
 * @param {{facts?: any, agents?: any[], now?: number}} input
 * @returns {Readout|null}
 */
export function surfaceReadout(id, input) {
  const facts = input.facts || {};
  const agents = input.agents || [];
  // How each list behind the faces was read (W12): 'pending', 'ok' or 'failed'. A face never
  // says its record is empty unless the record was read and is.
  const reads = facts.reads || {};
  const now = Number.isFinite(input.now) ? Number(input.now) : Date.now();
  const surface = SURFACES.find((s) => s.id === id);
  const action = surface ? openWords(surface.room) : '';

  if (id.startsWith('desk:')) {
    const agent = atDesk(agents, id.slice(5));
    if (!agent) return null;
    const mode = paneMode(agent);
    const monitor = { dark: 'stins', idle: 'aprins, fără lucru', work: 'lucrează', think: 'se gândește', error: 'eroare' }[mode];
    const state = String(agent.lifecycle || '').toUpperCase() === 'PAUSED' ? 'PAUSED' : String(agent.runtime_state || 'IDLE');
    const tasks = (facts.tasks && facts.tasks.tasks) || {};
    return keyed({
      id,
      eyebrow: 'MONITOR · BIROU',
      value: String(agent.display_name || agent.role_name || '—'),
      line: `${runtimeLabel(state)} · monitor ${monitor}`,
      context: lastTaskLine(tasks[agent.id || agent.agent_id], now),
      action: 'Clic: deschide fișa angajatului.',
      tone: mode === 'error' ? 'alert' : mode === 'work' || mode === 'think' ? 'ok' : 'quiet',
      poster: false,
    });
  }
  if (!surface) return null;

  if (id === 'treasury_board') {
    const face = treasuryFace(facts.treasury, facts.budget, facts.replay ? 'atunci' : 'azi');
    const known = Boolean(facts.treasury || facts.budget);
    return keyed({
      id,
      eyebrow: surface.name,
      value: face.balance === '—' ? '—' : `${face.balance} VR$ cheltuibili`,
      line: known ? face.line : reads.figures === 'failed' ? 'trezoreria nu a putut fi citită' : '',
      context: face.deficit ? 'Trezoreria este în deficit.' : facts.replay ? 'Soldul cheltuibil și cheltuiala zilei reluate, din registrul de atunci, până la acest moment.' : 'Soldul cheltuibil și cheltuiala de azi față de bugetul zilnic.',
      action,
      tone: face.deficit ? 'alert' : face.state && face.state !== 'OK' ? 'warn' : 'quiet',
      poster: false,
    });
  }
  if (id === 'run_sign') {
    const face = runSignFace(facts.track, { today: facts.today, live: facts.live, read: reads.runs });
    const running = face.underWay;
    const next = face.open ? '' : nextRunSign(facts.jobs, { stopped: facts.stopped, timeZone: facts.timeZone });
    return keyed({
      id,
      eyebrow: surface.name,
      value: face.tally === '—' ? face.state : `${face.title} · ${face.tally}`,
      line: face.tally === '—' ? '' : face.state,
      context: running ? 'O rulare este în lucru acum.' : face.open ? 'Rularea de azi nu s-a încheiat încă.' : next ? `${next[0].toUpperCase()}${next.slice(1)}.` : '',
      // While the studio rests and a finished day is on record, the sign's click plays that day
      // back from the record (W13, day_replay.js); while a run is under way it is live, not a replay.
      action: replayOffered(facts, face) ? REPLAY_ACTION : action,
      tone: running ? 'ok' : 'quiet',
      poster: false,
    });
  }
  if (id === 'factcheck_board') {
    const stage = facts.run && Array.isArray(facts.run.stages) ? facts.run.stages.find((/** @type {any} */ s) => s && s.stage === 'research_and_verification') : null;
    const a = (stage && stage.artefacts) || {};
    const n = (/** @type {any} */ v) => (v === null || v === undefined || !Number.isFinite(Number(v)) ? null : Math.floor(Number(v)));
    const verified = n(a.claims_verified);
    const refused = n(a.verdicts_refused);
    const face = factCheckFace(facts.run);
    return keyed({
      id,
      eyebrow: surface.name,
      value: verified === null && refused === null ? '—' : `${verified === null ? '—' : counted(verified, 'afirmație verificată', 'afirmații verificate')} · ${refused === null ? '—' : counted(refused, 'verdict respins', 'verdicte respinse')}`,
      line: face.date ? `rularea din ${face.date}` : facts.run ? 'cea mai nouă rulare nu are etapa de verificare' : listWords(reads.runs, 'nicio rulare în registru').replace(/^—$/, ''),
      context: 'Afirmațiile verificate și verdictele respinse ale celei mai noi rulări.',
      action,
      tone: 'quiet',
      poster: false,
    });
  }
  if (id === 'research_board') {
    const titles = (facts.topics && facts.topics.titles) || [];
    return keyed({
      id,
      eyebrow: surface.name,
      value: titles.length ? counted(titles.length, 'subiect propus', 'subiecte propuse') : reads.ledger === 'ok' ? 'niciun subiect propus în registru' : '—',
      line: titles.length ? `cel mai nou: ${titles[0]}` : reads.ledger === 'failed' ? NOT_READ : '',
      context: 'Subiectele propuse de Cercetător, câte unul pe fiecare notiță.',
      action,
      tone: 'quiet',
      poster: false,
    });
  }
  if (id === 'writers_screen') {
    const face = writersFace(facts.episodes);
    return keyed({
      id,
      eyebrow: surface.name,
      value: face.state ? `${face.number} · ${face.state}` : face.number,
      line: face.title || (facts.episodes ? '' : reads.episodes === 'failed' ? 'serialul nu a putut fi citit' : ''),
      context: 'Cel mai nou episod al serialului.',
      action,
      tone: 'quiet',
      poster: false,
    });
  }
  if (id === 'publish_radar') {
    const mode = paneMode(atDesk(agents, 'desk_publish'));
    const busy = mode === 'work' || mode === 'think';
    const face = publishFace(facts.run);
    const stage = facts.run && Array.isArray(facts.run.stages) ? facts.run.stages.find((/** @type {any} */ s) => s && s.stage === 'publish') : null;
    const title = stage && stage.artefacts && typeof stage.artefacts.title === 'string' ? stage.artefacts.title : '';
    return keyed({
      id,
      eyebrow: surface.name,
      value: busy ? 'ÎN LUCRU' : face.date ? `${face.word} · ${face.date}` : face.word,
      line: busy ? 'Publicatorul lucrează acum.' : title || (facts.run ? '' : listWords(reads.runs, 'nicio rulare în registru').replace(/^—$/, '')),
      context: 'Ce a publicat cea mai nouă rulare.',
      action,
      tone: busy ? 'ok' : face.word === 'EȘUAT' ? 'alert' : 'quiet',
      poster: false,
    });
  }
  if (id === 'infra_plate') {
    const face = tokensFace(facts.budget, facts.replay ? 'atunci' : 'azi');
    return keyed({
      id,
      eyebrow: surface.name,
      value: face.text,
      line: facts.budget ? '' : reads.figures === 'failed' ? 'bugetul nu a putut fi citit' : '',
      context: facts.replay ? 'Tokenurile folosite de angajați în ziua reluată, până la acest moment, din registrul de atunci.' : 'Tokenurile folosite azi de angajați, după bugetul de azi.',
      action,
      tone: 'quiet',
      poster: false,
    });
  }
  if (id === 'render_bay') {
    const editor = atDesk(agents, 'desk_video');
    const film = facts.film || null;
    const face = renderBayFace({ agent: editor, film });
    const who = editor && editor.display_name ? String(editor.display_name) : 'editorul video';
    let value;
    let line = '';
    if (face.kind === 'rendering') {
      value = face.word;
      line = face.detail || '';
    } else if (face.kind === 'poster') {
      value = face.caption;
      const sampled = Number(film && film.canvas && film.canvas.dataset ? film.canvas.dataset.sampled : 0);
      line = sampled > 1 ? `cel mai luminos dintre ${sampled} cadre-cheie ale filmului` : 'un cadru din fișierul filmului';
    } else {
      value = face.word;
      // Not read is not empty (W12): the record's film, or why there is no frame of it.
      const frame = reads.film;
      line = frame === 'failed'
        ? 'cadrul filmului nu a putut fi citit'
        : frame === 'pending'
          ? ''
          : listWords(reads.runs, 'niciun film randat în registru').replace(/^—$/, '');
    }
    return keyed({
      id,
      eyebrow: surface.name,
      value,
      line,
      context: `Ecranul arată randarea cât timp lucrează ${who}; altfel un cadru din cel mai nou film.`,
      action,
      tone: face.kind === 'rendering' ? 'ok' : face.kind === 'state' && face.fault ? 'alert' : 'quiet',
      poster: face.kind === 'poster',
    });
  }
  return null;
}

/**
 * The canvas's own name for assistive technology: the building, whether it is live, and what
 * the arrows walk (the employees, then the building's screens). index.html carries the same
 * sentence before the page is live; main.js rewrites it only through this (W11).
 * @param {boolean} live
 */
export function canvasLabel(live) {
  return `Sediul AMN-AI${live ? ', live' : ''}. Săgețile trec de la un angajat la altul, apoi prin ecranele clădirii; Enter deschide ce ai ales.`;
}

/** The readout as one sentence, for the polite live region. @param {Readout} r */
export function readoutSentence(r) {
  // the floor's code («L3», «S2») is for the eye; the ear gets the face's name
  const name = r.eyebrow.replace(/\s·\s[LS]\d$/, '').toLocaleLowerCase('ro-RO');
  return [name, r.value, r.line, r.context]
    .filter(Boolean)
    .map((part) => part.replace(/[.\s]+$/, ''))
    .join('. ')
    .concat('.');
}

/* ------------------------------------------------------------------------------------------
 * WHERE THE READOUT STANDS
 * ---------------------------------------------------------------------------------------- */

/**
 * Where the glass stands beside the surface it describes: inside the free room (the render less
 * the drawers, the sky row and the slate), never over the surface. Right of it first (the eye
 * reads on), then left, then above, then below; when no side holds it whole, the side with the
 * most room, pushed inside the room and still off the surface wherever the room allows.
 * @param {{x: number, y: number, w: number, h: number}} target the surface on screen
 * @param {{w: number, h: number}} size the readout
 * @param {{left: number, top: number, right: number, bottom: number}} room
 * @param {number} [gap]
 * @param {'right'|'left'|'above'|'below'} [prefer] the side to try first (the sign: below)
 * @returns {{x: number, y: number, side: 'right'|'left'|'above'|'below'}}
 */
export function placeReadout(target, size, room, gap = 12, prefer) {
  const clampX = (/** @type {number} */ x) => Math.max(room.left, Math.min(room.right - size.w, x));
  const clampY = (/** @type {number} */ y) => Math.max(room.top, Math.min(room.bottom - size.h, y));
  const midY = target.y + target.h / 2 - size.h / 2;
  const midX = target.x + target.w / 2 - size.w / 2;
  const sides = /** @type {const} */ ([
    { side: 'right', x: target.x + target.w + gap, y: clampY(midY), room: room.right - (target.x + target.w + gap) - size.w },
    { side: 'left', x: target.x - gap - size.w, y: clampY(midY), room: target.x - gap - size.w - room.left },
    { side: 'above', x: clampX(midX), y: target.y - gap - size.h, room: target.y - gap - size.h - room.top },
    { side: 'below', x: clampX(midX), y: target.y + target.h + gap, room: room.bottom - (target.y + target.h + gap) - size.h },
  ]);
  const order = prefer ? [...sides.filter((s) => s.side === prefer), ...sides.filter((s) => s.side !== prefer)] : sides;
  const fits = order.find((s) => s.room >= 0 && s.x >= room.left - 0.5 && s.x + size.w <= room.right + 0.5 && s.y >= room.top - 0.5 && s.y + size.h <= room.bottom + 0.5);
  const pick = fits || sides.reduce((a, b) => (b.room > a.room ? b : a));
  return { x: Math.round(clampX(pick.x)), y: Math.round(clampY(pick.y)), side: pick.side };
}

/**
 * The surface's rectangle on screen, in CSS px of the canvas box.
 * @param {number[]} rect world px @param {{zoom: number, panX: number, panY: number}} view canvas px
 * @param {number} dpr canvas px per CSS px
 */
export function screenRect(rect, view, dpr) {
  const [x, y, w, h] = rect;
  const k = view.zoom / (dpr || 1);
  return { x: (x * view.zoom + view.panX) / (dpr || 1), y: (y * view.zoom + view.panY) / (dpr || 1), w: w * k, h: h * k };
}

/* ------------------------------------------------------------------------------------------
 * THE GLINT: a face whose value changed while the page was watching
 * ---------------------------------------------------------------------------------------- */

/** How long the one glint lasts. */
export const GLINT_MS = 1400;

/** A face key that says the page does not hold the value: «—», none, empty. */
const UNKNOWN = /(^|\|)(—|none|empty)(\||$)|^nb\|$/;

/**
 * Remembers each face's key and says when one changed live: not on the first value a face is
 * given (the page reading the studio at the key), not from or to a value the page does not hold
 * (a read arriving, a reset), only a known value becoming another one after the page settled.
 */
export class GlintTracker {
  /** @param {number} [settleMs] how long after the first key the page is still arriving */
  constructor(settleMs = 6000) {
    /** @type {Map<string, string>} */
    this.keys = new Map();
    /** @type {Map<string, number>} */
    this.since = new Map();
    this.settleMs = settleMs;
    /** @type {number|null} */
    this.firstAt = null;
  }

  /**
   * @param {string} id @param {string} key @param {number} now
   * @returns {boolean} whether this is a live change that should glint
   */
  note(id, key, now) {
    if (this.firstAt === null) this.firstAt = now;
    const before = this.keys.get(id);
    this.keys.set(id, key);
    if (before === undefined || before === key) return false;
    if (now - this.firstAt < this.settleMs) return false;
    if (UNKNOWN.test(key) || UNKNOWN.test(before)) return false;
    this.since.set(id, now);
    return true;
  }

  /**
   * A glint asked for by a live event rather than a changed key (W12: a stage that starts,
   * live, glints the façade sign even when its words were already the same).
   * @param {string} id @param {number} now
   */
  force(id, now) {
    this.since.set(id, now);
  }

  /** 0..1 of the glint under way on a face, or null. @param {string} id @param {number} now */
  progress(id, now) {
    const at = this.since.get(id);
    if (at === undefined) return null;
    const t = (now - at) / GLINT_MS;
    if (t >= 1 || t < 0) {
      this.since.delete(id);
      return null;
    }
    return t;
  }

  /** Forget everything (a new key, a new studio). */
  reset() {
    this.keys.clear();
    this.since.clear();
    this.firstAt = null;
  }
}
