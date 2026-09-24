/**
 * THE SCREENS OF THE BUILDING SHOW THE STUDIO'S TRUTH (W7).
 *
 * Every surface in the plates that reads as a screen, a board or a display is bound here to one
 * value the page really holds, or to nothing:
 *
 *   - each monitor on a desk: dark while the desk is empty or its employee is paused, an idle
 *     glow while the employee is IDLE, lit and flickering with work only while WORKING (a slow
 *     pulse while THINKING, red while in error). The plates bake working screens (charts, code)
 *     into every monitor; those are covered, so a monitor never shows work nobody is doing;
 *   - the render bay's wall display: while the Video Editor works, the render's own state; when
 *     not, a frame of the newest film the runbook recorded as rendered (decoded by film_poster.js
 *     from the file itself); without one, the editor's state in words;
 *   - the Treasury's wall ticker: the spendable VR$ balance (/economy/treasury) and today's spend
 *     against the daily budget (/economy/budget), in numbers.js's Romanian figures;
 *   - the façade sign's free right half: the day's run track, the same segments and words as the
 *     slate (hud_charts.js), from the runbook's events and its record;
 *   - the fact-check whiteboard: the newest run's verified claims and refused verdicts (the
 *     research stage's own artefacts);
 *   - the research cork board: the newest topics the Researcher proposed (factual.topic_proposed),
 *     one note each; a note with no topic is blank paper;
 *   - the writers' room wall screen: the serial's newest episode, its number and state;
 *   - the distribution radar: the newest run's publication state;
 *   - the server room's header plate: tokens the employees used today;
 *   - each room's light: full while someone there works, lower while its people sit idle, low
 *     when nobody is at a desk, within the building's day or night.
 *
 * A value the page does not have is never invented: the surface stays dark or shows «—».
 * Everything that decides what a surface shows is a pure function below (value -> face), with node
 * tests; the drawing of a face is cached in its own canvas and redrawn only when the face's key or
 * the display scale changes. Only a working monitor's lines and the running segment of the day
 * move per frame, and under reduced motion they hold still.
 *
 * The rectangles were measured off the plates (art-source/blender/hq, exported 2026-09-13 and
 * 2026-09-24). They belong in manifest.json the next time the art build exports it.
 */

import { amount } from './numbers.js';
import { runtimeLabel, taskLabel } from './ledger.js';
import { dayTrackWords, shortDate } from './hud_charts.js';
import { STATUS_WORD } from './serial_room.js';

/* ------------------------------------------------------------------------------------------
 * WHERE THE SURFACES STAND, IN WORLD PX
 * ---------------------------------------------------------------------------------------- */

/**
 * The single screens inside each of the manifest's screen rectangles. A manifest rectangle
 * around a row of monitors also spans the wall between them; covering it whole would join the
 * monitors into one bar, so each monitor is its own pane.
 * @type {Record<string, Array<[number, number, number, number]>>}
 */
export const PANES = {
  director_monitors: [[772.5, 128.8, 23, 12.6], [799.5, 128.8, 23.5, 12.6], [826.5, 128.8, 23, 12.6]],
  research_monitors: [[658, 234.8, 24, 12.2], [688.5, 234.8, 23.5, 12.2]],
  factcheck_monitors: [[893, 234.8, 24, 12.2], [921.2, 234.8, 26.8, 12.2]],
  script_monitors: [[764.5, 337.6, 39.5, 17.4], [806, 337.6, 40, 17.4]],
  audio_monitors: [[642, 452.8, 25.5, 11.2], [681, 452.8, 23.5, 11.2]],
  video_monitors: [[989.5, 452.8, 21, 12.2], [1012.5, 452.8, 21, 12.2], [1035.5, 452.8, 21, 12.2]],
  treasury_monitor: [[934.2, 604, 18.6, 10]],
  video_wall: [[1074, 438, 26.5, 24.5]],
};

/** The monitors that stand on the desks, in the desks' plate (building_front), in front of the employee. */
export const DESK_MONITOR = /^desk_.+_monitor$/;

/**
 * A desk monitor's glass: the monitor is turned a little towards its employee, so its glass is a
 * quad, not a rectangle (measured on the director's, the video editor's, the publisher's and the
 * accountant's monitors: the left edge stands lower and longer than the right).
 * @param {number[]} rect the manifest's rectangle
 * @returns {Array<[number, number]>} top-left, top-right, bottom-right, bottom-left
 */
export function deskPane(rect) {
  const [x, y, w, h] = rect;
  return [[x + 1, y + 1.4], [x + w - 0.3, y + 0.2], [x + w - 0.3, y + h - 1.3], [x + 1, y + h - 0.5]];
}

/** Screens the manifest does not list, with the desk whose employee they follow. */
export const EXTRA_SCREENS = {
  video_wall: { rect: [1074, 438, 26.5, 24.5], zone: 'video_studio', desk: 'desk_video' },
};

/** The bound walls. */
export const WALL = {
  treasury_board: [1004, 601, 23.5, 22.8],
  factcheck_board: [972, 210, 28.5, 39.5],
  writers_screen: [777.5, 301.5, 57.5, 26.5],
  run_sign: [1066, 45, 132, 30],
  infra_plate: [549, 522, 84, 13],
};

/** The research board's six notes. */
export const NOTES = [
  [754, 213, 22.5, 12], [786, 213, 22.2, 12], [815, 213, 22.5, 12],
  [754.5, 230, 22.5, 12], [786.5, 230, 22.3, 12], [818.5, 230, 22.5, 12],
];

/* ------------------------------------------------------------------------------------------
 * VALUE -> FACE (pure)
 * ---------------------------------------------------------------------------------------- */

const WORK = new Set(['WORKING', 'EXECUTING', 'RUNNING']);
const THINK = new Set(['THINKING', 'PLANNING', 'REVIEWING']);
const FAULT = new Set(['ERROR', 'BLOCKED', 'FAILED']);

/** @param {any} agent */
function stateOf(agent) {
  const lifecycle = String(agent?.lifecycle || '').toUpperCase();
  if (lifecycle === 'PAUSED' || lifecycle === 'SUSPENDED') return 'PAUSED';
  return String(agent?.runtime_state || 'IDLE').toUpperCase();
}

/**
 * What a monitor shows for the employee at its desk.
 * @param {any} agent null when the desk is empty
 * @returns {'dark'|'idle'|'work'|'think'|'error'}
 */
export function paneMode(agent) {
  if (!agent) return 'dark';
  const state = stateOf(agent);
  if (state === 'PAUSED') return 'dark';
  if (WORK.has(state)) return 'work';
  if (THINK.has(state)) return 'think';
  if (FAULT.has(state)) return 'error';
  return 'idle';
}

/**
 * Whether anyone works in a room: 'working' while an employee seated there works or thinks,
 * 'present' while its people sit idle (or in error), 'empty' with nobody at a desk.
 * @param {any[]} agents the room's seated employees
 * @returns {'working'|'present'|'empty'}
 */
export function roomOccupancy(agents) {
  const list = (agents || []).filter(Boolean);
  const modes = list.map(paneMode);
  if (modes.some((m) => m === 'work' || m === 'think')) return 'working';
  if (modes.some((m) => m !== 'dark')) return 'present';
  return 'empty';
}

/** How far a room's lights are lowered, 0 = as the plates light it. */
export const ROOM_SHADE = { night: { working: 0, present: 0.2, empty: 0.5 }, day: { working: 0, present: 0.04, empty: 0.14 } };

/**
 * @param {'working'|'present'|'empty'} occupancy
 * @param {number} daylight 0 night .. 1 day
 * @returns {number} the alpha of the dark laid over the room
 */
export function roomShade(occupancy, daylight) {
  const d = Math.max(0, Math.min(1, Number(daylight) || 0));
  const night = ROOM_SHADE.night[occupancy] ?? 0;
  const day = ROOM_SHADE.day[occupancy] ?? 0;
  return Math.round((night + (day - night) * d) * 1000) / 1000;
}

/**
 * How a lit screen sits in the light: by day the sun washes it out and it casts nothing; at night
 * it glows onto its wall.
 * @param {number} daylight
 */
export function screenLight(daylight) {
  const d = Math.max(0, Math.min(1, Number(daylight) || 0));
  return { washout: Math.round(0.1 * d * 1000) / 1000, bloom: Math.round((1 - d) ** 1.5 * 1000) / 1000 };
}

/**
 * The newest film the runbook recorded as rendered: the media stage of the newest run that has
 * one (/runbook/runs, newest first).
 * @param {any[]|null|undefined} runs
 * @returns {{assetId: string, date: string|null}|null}
 */
export function latestFilm(runs) {
  for (const run of Array.isArray(runs) ? runs : []) {
    const media = (run?.stages || []).find((/** @type {any} */ s) => s && s.stage === 'media');
    const assets = media && media.artefacts && Array.isArray(media.artefacts.assets) ? media.artefacts.assets : [];
    const last = assets.filter((/** @type {any} */ a) => typeof a === 'string' && a).at(-1);
    if (last) return { assetId: last, date: typeof run.business_date === 'string' ? run.business_date : null };
  }
  return null;
}

/**
 * The render bay's display.
 * @param {{agent?: any, film?: {canvas?: any, date?: string|null, assetId?: string}|null}} input
 */
export function renderBayFace(input) {
  const agent = input.agent || null;
  const state = agent ? stateOf(agent) : null;
  const word = state ? runtimeLabel(state).toLocaleUpperCase('ro-RO') : '—';
  if (state && WORK.has(state)) {
    const detail = String(agent.detail || (agent.task_type ? taskLabel(agent.task_type) : '')).slice(0, 26);
    return { kind: 'rendering', word, detail, key: `r|${word}|${detail}` };
  }
  const film = input.film;
  if (film && film.canvas) {
    const date = shortDate(film.date || '');
    return { kind: 'poster', word, caption: date ? `ultimul film · ${date}` : 'ultimul film', key: `p|${film.assetId || ''}|${date}|${word}` };
  }
  const fault = state ? FAULT.has(state) : false;
  return { kind: 'state', word, fault, key: `s|${word}|${fault}` };
}

/**
 * The Treasury's wall ticker.
 * @param {any} treasury /economy/treasury
 * @param {any} budget /economy/budget
 */
export function treasuryFace(treasury, budget) {
  const cash = treasury && treasury.spendable ? String(treasury.spendable.amount ?? '') : '';
  const balance = /^[+-]?\d+(\.\d+)?$/.test(cash) ? amount(wholeOrCents(cash)) : '—';
  const deficit = Boolean(treasury && treasury.in_deficit);
  const daily = budget && Array.isArray(budget.budgets) ? budget.budgets.find((/** @type {any} */ b) => b && b.period === 'DAILY' && b.active !== false) : null;
  const spentRaw = daily ? daily.spent_usd : budget && budget.today ? budget.today.spent_usd : null;
  const spent = spentRaw !== null && spentRaw !== undefined && /^\d+(\.\d+)?$/.test(String(spentRaw)) ? amount(wholeOrCents(String(spentRaw))) : '—';
  const limit = daily && /^\d+(\.\d+)?$/.test(String(daily.limit_usd)) ? amount(wholeOrCents(String(daily.limit_usd))) : null;
  const ratio = daily && Number.isFinite(Number(daily.ratio)) ? Math.max(0, Math.min(1, Number(daily.ratio))) : null;
  const state = daily ? String(daily.state || 'OK') : null;
  const line = spent === '—' ? 'azi —' : limit ? `azi ${spent} / ${limit} USD` : `azi ${spent} USD · fără buget`;
  return { balance, deficit, line, ratio, state, key: `t|${balance}|${deficit}|${line}|${ratio}|${state}` };
}

/**
 * A money figure for a small screen: whole units as they are, and at most two decimals (the
 * digits kept are the ledger's own, truncated, never rounded up).
 * @param {string} text
 */
export function wholeOrCents(text) {
  const [whole, fraction = ''] = String(text).split('.');
  // cut to two digits first, then drop the zeros that are left: 0.009 is 0, not «0,00»
  const cents = fraction.slice(0, 2).replace(/0+$/, '');
  return cents ? `${whole}.${cents}` : whole;
}

/**
 * The façade's run track: the slate's own segments and words. While no run is under way, the
 * state line also says what comes next, in the scheduler's own words (hq_readouts.js
 * nextRunSign): «încheiată · următoarea rulare vin. 25.09, 05:00», or that the daily schedule is
 * stopped. Never a countdown to a time nobody set.
 * @param {import('./hud_charts.js').DayTrack|null|undefined} track
 * @param {{today?: string|null, live?: boolean, next?: string}} [context]
 */
export function runSignFace(track, context = {}) {
  const next = context.next || '';
  if (!track || track.empty) return { title: 'RULAREA ZILEI', tally: '—', state: next || 'nicio rulare în registru', segments: [], running: -1, underWay: false, open: false, key: `rs|empty|${next}` };
  const words = dayTrackWords(track, context);
  const [title, tally, ...rest] = words.label.split(' · ');
  const segments = track.segments.map((s) => s.state);
  const running = segments.indexOf('running');
  // Under way: a stage is running now (the page's own live rule). Open: today's run has started
  // and not finished, even between two stages when no segment is lit; while it is open the sign
  // says no next run (W11). An unfinished run of another day is neither.
  const underWay = running >= 0 && context.live !== false;
  const open = !track.finished && (underWay || Boolean(track.date && context.today && track.date === context.today));
  const state = [rest.join(' · '), open ? '' : next].filter(Boolean).join(' · ');
  const face = { title: title.toLocaleUpperCase('ro-RO'), tally, state, segments, running, underWay, open };
  return { ...face, key: `rs|${face.title}|${tally}|${face.state}|${segments.join(',')}` };
}

/**
 * The fact-check whiteboard: the research stage of the newest run.
 * @param {any} run /runbook/runs -> runs[0]
 */
export function factCheckFace(run) {
  const stage = run && Array.isArray(run.stages) ? run.stages.find((/** @type {any} */ s) => s && s.stage === 'research_and_verification') : null;
  const a = (stage && stage.artefacts) || {};
  const verified = Number.isFinite(Number(a.claims_verified)) && a.claims_verified !== null && a.claims_verified !== undefined ? amount(String(Math.floor(Number(a.claims_verified)))) : '—';
  const refused = Number.isFinite(Number(a.verdicts_refused)) && a.verdicts_refused !== null && a.verdicts_refused !== undefined ? amount(String(Math.floor(Number(a.verdicts_refused)))) : '—';
  const date = stage ? shortDate(run.business_date) : '';
  return { verified, refused, date, key: `fc|${verified}|${refused}|${date}` };
}

/**
 * The research board: the newest topics proposed, newest first, at most six.
 * @param {any[]} events the register, newest first
 * @returns {{titles: string[], key: string}}
 */
export function boardTopics(events) {
  const titles = [];
  for (const event of Array.isArray(events) ? events : []) {
    if (!event || event.event_type !== 'factual.topic_proposed') continue;
    const title = String((event.payload && event.payload.title) || '').trim();
    if (title) titles.push(title);
    if (titles.length === NOTES.length) break;
  }
  return { titles, key: `nb|${titles.join('\u0001')}` };
}

/**
 * The writers' room screen: the newest episode of the serial.
 * @param {any} episodes /story/episodes
 */
export function writersFace(episodes) {
  const list = episodes && Array.isArray(episodes.episodes) ? episodes.episodes.slice() : null;
  if (!list) return { number: '—', state: '', title: '', key: 'w|none' };
  if (!list.length) return { number: '—', state: 'niciun episod', title: '', key: 'w|empty' };
  list.sort((a, b) => Date.parse(String(b.created_at || '')) - Date.parse(String(a.created_at || '')));
  const newest = list[0];
  const n = newest.continuity && typeof newest.continuity.episode_number === 'number' ? newest.continuity.episode_number : null;
  const status = String(newest.status || '');
  const state = /** @type {Record<string,string>} */ (STATUS_WORD)[status] || status.toLowerCase();
  const title = String(newest.title || '').trim();
  const number = n !== null ? `EP ${n}` : 'EP —';
  return { number, state, title, key: `w|${number}|${state}|${title}` };
}

/**
 * A publication's state on the radar, in the register's words. A simulated upload is not a
 * video on the channel: it never reads «PUBLICAT» (backend publishing LIVE_PUBLICATION_STATES).
 */
export const PUBLICATION_WORD = {
  PUBLISHED: 'PUBLICAT',
  REMOTE_CONFIRMED: 'PUBLICAT',
  PUBLISHED_SIMULATED: 'SIMULAT',
  SCHEDULED: 'PROGRAMAT',
  STARTED: 'ÎN CURS',
  REMOTE_UNKNOWN: 'NECONFIRMAT',
  VALIDATED: 'VALIDAT',
  BLOCKED: 'BLOCAT',
  FAILED: 'EȘUAT',
};

/**
 * The distribution radar when the Publisher is not at work: what the newest run published.
 * @param {any} run
 */
export function publishFace(run) {
  const stage = run && Array.isArray(run.stages) ? run.stages.find((/** @type {any} */ s) => s && s.stage === 'publish') : null;
  if (!stage) return { word: '—', date: '', key: 'pb|none' };
  const status = String((stage.artefacts && stage.artefacts.publication_status) || '');
  const word = status ? /** @type {Record<string,string>} */ (PUBLICATION_WORD)[status] || status : 'NIMIC PUBLICAT';
  const date = shortDate(run.business_date);
  return { word, date, key: `pb|${word}|${date}` };
}

/**
 * Tokens the employees used today (/economy/budget -> today).
 * @param {any} budget
 */
export function tokensFace(budget) {
  const today = budget && budget.today;
  const p = today ? Number(today.prompt_tokens) : NaN;
  const c = today ? Number(today.completion_tokens) : NaN;
  if (!Number.isFinite(p) || !Number.isFinite(c)) return { text: 'tokenuri azi —', key: 'tk|none' };
  const n = Math.max(0, Math.floor(p + c));
  const rest = n % 100;
  const noun = n === 1 ? 'token azi' : `${n >= 20 && (rest === 0 || rest >= 20) ? 'de ' : ''}tokenuri azi`;
  const text = `${amount(String(n))} ${noun}`;
  return { text, key: `tk|${text}` };
}

/* ------------------------------------------------------------------------------------------
 * THE DRAWING CACHE
 * ---------------------------------------------------------------------------------------- */

/**
 * One canvas per surface, drawn at the display scale and redrawn only when what it shows (its
 * key) or the scale bucket changes. While the zoom is moving the last drawing is stretched.
 */
export class FaceCache {
  constructor() {
    /** @type {Map<string, {key: string, canvas: any}>} */
    this.entries = new Map();
    this.redraws = 0;
  }

  /**
   * @param {string} id
   * @param {string} key what the face shows
   * @param {number} w @param {number} h the surface in world px
   * @param {number} scale canvas px per world px
   * @param {(c: CanvasRenderingContext2D, w: number, h: number) => void} paint draws in world px
   */
  get(id, key, w, h, scale, paint) {
    if (typeof document === 'undefined') return null;
    const bucket = Math.min(8, Math.max(1, Math.ceil(scale * 2) / 2));
    const full = `${key}@${bucket}`;
    const hit = this.entries.get(id);
    if (hit && hit.key === full) return hit.canvas;
    const canvas = hit ? hit.canvas : document.createElement('canvas');
    canvas.width = Math.max(1, Math.ceil(w * bucket));
    canvas.height = Math.max(1, Math.ceil(h * bucket));
    const c = canvas.getContext('2d');
    if (!c) return null;
    c.setTransform(bucket, 0, 0, bucket, 0, 0);
    c.clearRect(0, 0, w, h);
    paint(c, w, h);
    this.entries.set(id, { key: full, canvas });
    this.redraws += 1;
    return canvas;
  }
}

/* ------------------------------------------------------------------------------------------
 * PAINTERS (a face, drawn in the surface's own world px)
 * ---------------------------------------------------------------------------------------- */

const DISPLAY = '"Oxanium", "Segoe UI", system-ui, sans-serif';
const SANS = '"Segoe UI", system-ui, sans-serif';

/** Text shrunk until it fits the width. @param {CanvasRenderingContext2D} c */
function fitText(c, text, x, y, maxW, weight, size, family, min = 2) {
  let s = size;
  c.font = `${weight} ${s}px ${family}`;
  while (s > min && c.measureText(text).width > maxW) {
    s -= 0.25;
    c.font = `${weight} ${s}px ${family}`;
  }
  c.fillText(text, x, y);
}

/** A screen's glass: a dark panel with the faint gradient of a lit LCD. @param {CanvasRenderingContext2D} c */
function glass(c, w, h, top, bottom) {
  const g = c.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, top);
  g.addColorStop(1, bottom);
  c.fillStyle = g;
  c.fillRect(0, 0, w, h);
}

/** @param {CanvasRenderingContext2D} c @param {any} face */
export function paintTreasury(c, w, h, face) {
  glass(c, w, h, '#0e2412', '#07140a');
  c.textAlign = 'left';
  c.textBaseline = 'alphabetic';
  c.fillStyle = '#7fae66';
  fitText(c, 'TREZORERIE · VR$', 1.4, 4.4, w - 2.8, 600, 3.2, DISPLAY, 2);
  c.fillStyle = face.deficit ? '#ff9d8f' : '#d7f7b8';
  fitText(c, face.balance, 1.4, 11.6, w - 2.8, 700, 7.2, DISPLAY, 3);
  // today's spend against the daily budget
  const y = 14.2;
  c.fillStyle = 'rgba(160,220,130,0.18)';
  c.fillRect(1.4, y, w - 2.8, 1.6);
  if (face.ratio !== null) {
    c.fillStyle = face.state === 'OK' ? '#8fd46a' : face.state === 'WARN' || face.state === 'WARNING' ? '#f0c887' : '#ff9d8f';
    c.fillRect(1.4, y, Math.max(face.ratio > 0 ? 0.6 : 0, (w - 2.8) * face.ratio), 1.6);
  }
  c.fillStyle = '#a9d68d';
  fitText(c, face.line, 1.4, 20.2, w - 2.8, 600, 3.1, SANS, 1.8);
}

/** @param {CanvasRenderingContext2D} c @param {any} face @param {any} palette */
export function paintRunSign(c, w, h, face, palette) {
  // the sign's own black and its cream letters
  c.fillStyle = '#121212';
  c.fillRect(0, 0, w, h);
  c.textBaseline = 'alphabetic';
  c.fillStyle = '#efe2c8';
  c.textAlign = 'left';
  c.font = `700 6px ${DISPLAY}`;
  spaced(c, face.title, 2, 9.5, 0.9);
  c.textAlign = 'right';
  c.font = `700 8px ${DISPLAY}`;
  c.fillText(face.tally, w - 2, 10);
  const n = face.segments.length;
  const colours = {
    done: palette.okInk, partial: palette.warnInk, failed: palette.alertInk, skipped: palette.chromeMuted,
    running: palette.gold, pending: palette.segPending, unrun: palette.segUnrun,
  };
  if (n) {
    const gap = 1.6;
    const sw = (w - 4 - gap * (n - 1)) / n;
    face.segments.forEach((/** @type {string} */ s, /** @type {number} */ i) => {
      c.fillStyle = /** @type {Record<string,string>} */ (colours)[s] || colours.pending;
      c.fillRect(2 + i * (sw + gap), 13.5, sw, 5);
    });
  } else {
    c.fillStyle = colours.unrun;
    c.fillRect(2, 13.5, w - 4, 5);
  }
  c.textAlign = 'left';
  c.fillStyle = '#cdbfa6';
  fitText(c, face.state, 2, 26.8, w - 4, 600, 6, SANS, 3);
}

/** @param {CanvasRenderingContext2D} c @param {string} text */
function spaced(c, text, x, y, spacing) {
  let at = x;
  for (const ch of text) {
    c.fillText(ch, at, y);
    at += c.measureText(ch).width + spacing;
  }
}

/** The whiteboard, in marker. @param {CanvasRenderingContext2D} c @param {any} face */
export function paintFactCheck(c, w, h, face) {
  const g = c.createLinearGradient(0, 0, w, h);
  g.addColorStop(0, '#f7f8fa');
  g.addColorStop(1, '#e6e9ee');
  c.fillStyle = g;
  c.fillRect(0, 0, w, h);
  c.textBaseline = 'alphabetic';
  c.textAlign = 'left';
  c.fillStyle = '#3b4658';
  fitText(c, 'VERIFICAREA', 2, 5, w - 4, 700, 3.4, SANS, 2);
  fitText(c, face.date ? `FAPTELOR · ${face.date}` : 'FAPTELOR', 2, 9, w - 4, 700, 3.4, SANS, 2);
  c.fillStyle = '#1f7a4d';
  fitText(c, face.verified, 2, 19.5, w - 4, 800, 9, SANS, 4);
  c.fillStyle = '#3b4658';
  c.font = `600 3.2px ${SANS}`;
  c.fillText('verificate', 2, 23.5);
  c.fillStyle = '#b3362b';
  fitText(c, face.refused, 2, 33, w - 4, 800, 9, SANS, 4);
  c.fillStyle = '#3b4658';
  c.font = `600 3.2px ${SANS}`;
  fitText(c, 'verdicte respinse', 2, 37, w - 4, 600, 3.2, SANS, 2);
}

/** One note of the research board. @param {CanvasRenderingContext2D} c @param {string} title */
export function paintNote(c, w, h, title) {
  c.fillStyle = '#f2f3f4';
  c.fillRect(0, 0, w, h);
  if (!title) return;
  c.fillStyle = '#2f3a4c';
  c.textAlign = 'left';
  c.textBaseline = 'alphabetic';
  c.font = `600 2.35px ${SANS}`;
  const lines = wrap(c, title, w - 2.4, 4);
  lines.forEach((line, i) => c.fillText(line, 1.2, 3.2 + i * 2.75));
}

/** @param {CanvasRenderingContext2D} c @param {string} text @param {number} maxW @param {number} maxLines */
function wrap(c, text, maxW, maxLines) {
  const words = text.split(/\s+/);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (c.measureText(next).width <= maxW || !line) line = next;
    else {
      lines.push(line);
      line = word;
    }
    if (lines.length === maxLines) break;
  }
  if (lines.length < maxLines && line) lines.push(line);
  if (lines.length === maxLines && words.join(' ') !== lines.join(' ')) lines[maxLines - 1] = `${lines[maxLines - 1].replace(/\s*\S*$/, '')}…`;
  return lines;
}

/** @param {CanvasRenderingContext2D} c @param {any} face */
export function paintWriters(c, w, h, face) {
  glass(c, w, h, '#101a2e', '#070c18');
  c.textBaseline = 'alphabetic';
  c.textAlign = 'left';
  c.fillStyle = '#5fd4c0';
  c.font = `700 3.6px ${DISPLAY}`;
  spaced(c, 'OFFICE SERIAL', 2.5, 6, 0.5);
  c.fillStyle = '#f2f5fb';
  fitText(c, face.number, 2.5, 16.5, 26, 700, 10, DISPLAY, 5);
  c.fillStyle = '#e0b062';
  c.textAlign = 'right';
  fitText(c, face.state, w - 2.5, 16, 26, 700, 4.2, SANS, 2.5);
  c.textAlign = 'left';
  c.fillStyle = '#aab6cc';
  fitText(c, face.title || '', 2.5, 23.5, w - 5, 500, 3.3, SANS, 2);
}

/** @param {CanvasRenderingContext2D} c @param {any} face */
export function paintPublish(c, w, h, face) {
  glass(c, w, h, '#0a1f17', '#05120c');
  c.textAlign = 'center';
  c.textBaseline = 'alphabetic';
  c.fillStyle = '#4ade80';
  c.font = `600 3.2px ${DISPLAY}`;
  c.fillText('DISTRIBUȚIE', w / 2, 6);
  c.fillStyle = '#d9fbe6';
  fitText(c, face.word, w / 2, 15.5, w - 4, 700, 5, DISPLAY, 2.5);
  c.fillStyle = '#7fcaa0';
  c.font = `600 3.6px ${SANS}`;
  if (face.date) c.fillText(face.date, w / 2, 22);
  c.textAlign = 'left';
}

/** @param {CanvasRenderingContext2D} c @param {any} face */
export function paintInfra(c, w, h, face) {
  c.textBaseline = 'alphabetic';
  c.textAlign = 'right';
  c.fillStyle = '#c9d3e6';
  fitText(c, face.text, w - 1, 10, w - 2, 700, 6.4, DISPLAY, 3);
  c.textAlign = 'left';
}

/**
 * The render bay's display, whatever it shows but the moving band.
 * @param {CanvasRenderingContext2D} c @param {any} face @param {any} poster a canvas or null
 */
export function paintRenderBay(c, w, h, face, poster) {
  c.fillStyle = face.kind === 'rendering' ? '#071a2c' : '#050a12';
  c.fillRect(0, 0, w, h);
  c.textAlign = 'center';
  c.textBaseline = 'alphabetic';
  c.fillStyle = '#9fb4cc';
  c.font = `600 6px ${SANS}`;
  c.fillText('RANDARE', w / 2, 9);
  if (face.kind === 'poster' && poster) {
    // the film is 9:16; the poster stands in the middle of the panel
    const ph = 38;
    const pw = (ph * 9) / 16;
    c.drawImage(poster, (w - pw) / 2, 12, pw, ph);
    c.strokeStyle = 'rgba(159,180,204,0.35)';
    c.lineWidth = 0.4;
    c.strokeRect((w - pw) / 2, 12, pw, ph);
    c.fillStyle = '#9fb4cc';
    fitText(c, face.caption, w / 2, 56, w - 4, 600, 4.2, SANS, 2.5);
  } else if (face.kind === 'rendering') {
    c.fillStyle = '#e6f1ff';
    fitText(c, face.word, w / 2, 24, w - 6, 700, 9, SANS, 5);
    c.strokeStyle = '#38bdf8';
    c.lineWidth = 0.8;
    c.strokeRect(8, 33, w - 16, 6);
    if (face.detail) {
      c.fillStyle = '#9fb4cc';
      fitText(c, face.detail, w / 2, 49, w - 6, 500, 5, SANS, 3);
    }
  } else {
    c.fillStyle = face.fault ? '#fca5a5' : '#7890ab';
    fitText(c, face.word, w / 2, 27, w - 6, 700, 9, SANS, 5);
  }
  c.textAlign = 'left';
}

/**
 * One monitor, by mode. Only 'work' and 'think' move, and only while the clock does.
 * @param {CanvasRenderingContext2D} ctx world transform
 * @param {[number, number, number, number]} r
 * @param {'dark'|'idle'|'work'|'think'|'error'} mode
 * @param {string} accent "r,g,b"
 * @param {number} clock seconds of the world's ambient clock (frozen under reduced motion)
 * @param {number} seed
 */
export function drawPane(ctx, r, mode, accent, clock, seed) {
  const [x, y, w, h] = r;
  if (mode === 'dark') {
    ctx.fillStyle = '#05070c';
    ctx.fillRect(x, y, w, h);
    // the glass still catches the room: one faint diagonal
    ctx.fillStyle = 'rgba(255,255,255,0.035)';
    ctx.beginPath();
    ctx.moveTo(x + w * 0.55, y);
    ctx.lineTo(x + w * 0.75, y);
    ctx.lineTo(x + w * 0.45, y + h);
    ctx.lineTo(x + w * 0.25, y + h);
    ctx.fill();
    return;
  }
  if (mode === 'error') {
    ctx.fillStyle = '#1a0708';
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = `rgba(239,68,68,${0.3 + 0.15 * Math.sin(clock * 4 + seed)})`;
    ctx.fillRect(x, y, w, h);
    return;
  }
  // idle: the lit screen of an unused desktop, no content
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  g.addColorStop(0, mode === 'idle' ? '#17253d' : '#132a4a');
  g.addColorStop(1, mode === 'idle' ? '#0c1526' : '#0a1830');
  ctx.fillStyle = g;
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = `rgba(${accent},${mode === 'idle' ? 0.22 : 0.4})`;
  ctx.fillRect(x, y, w, Math.min(1.2, h * 0.1));
  if (mode === 'idle') {
    ctx.fillStyle = `rgba(${accent},0.12)`;
    ctx.fillRect(x + w / 2 - 1, y + h / 2 - 1, 2, 2);
    return;
  }
  // work: lines of work scrolling up, and the flicker of a busy screen; think: slow and faint
  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
  const busy = mode === 'work';
  const speed = busy ? 9 : 1.6;
  const rows = Math.max(3, Math.floor(h / 2.1));
  for (let i = 0; i < rows + 1; i += 1) {
    const yy = y + 1.8 + (((i * 2.1 - clock * speed) % (rows * 2.1)) + rows * 2.1) % (rows * 2.1);
    const len = 0.25 + (((i * 37 + seed * 13) % 50) / 100) * (busy ? 1.2 : 0.7);
    ctx.fillStyle = `rgba(${accent},${busy ? 0.75 : 0.35})`;
    ctx.fillRect(x + 1 + ((i * 3 + seed) % 3), yy, Math.min(w - 2, w * len), 0.9);
  }
  const flicker = busy ? 0.08 + 0.06 * Math.abs(Math.sin(clock * 11 + seed)) : 0.04 + 0.04 * Math.sin(clock * 1.5 + seed);
  ctx.fillStyle = `rgba(${accent},${flicker})`;
  ctx.fillRect(x, y, w, h);
  ctx.restore();
}
