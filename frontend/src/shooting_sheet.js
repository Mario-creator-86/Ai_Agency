import { APPROVAL_DECISION_PATH, approvalDecisionCommand } from './governance.js';
import { paidMediaFormHtml, paidMediaRuleWords } from './owner_controls.js';
import { sheetKeyFor } from './sheet_key.js';

/** The film a letter, a question or a run names (sheet_key.js), so each can open its sheet. */
export { sheetKeyFor };

/**
 * FOAIA DE FILMARE — the page in front of every purchase of a film (SHEET_DRAWER, 2026-10-01).
 *
 * The Nepal film (2026-09-26) was bought twice from a button that showed no price, no prompt and
 * no model, and asked nothing. In PRODUCTION that button now answers 409 «Folosește foaia de
 * filmare» (backend media/router.py), and the page opens this drawer in its place.
 *
 * Everything shown is the backend's GET /media/storyboards/{id}/shooting-sheet (shooting_sheet.py
 * build_sheet, 0 credits: its only live call is the free Runway balance read): per scene its frame,
 * the model chosen for THAT scene with its resolution, billed seconds and credits, why, the cheaper
 * and the better model, the check badges, the prompt lint, the approved still and the candidates
 * refused with their reasons, both prompts exactly as they will be sent; and the footer the backend
 * priced. The page computes no price of its own: it only words the backend's figures and decides
 * which buttons may be pressed.
 *
 * Each paid step (stills, the hero test shot, the rest of the motion) is one «Aprobă …» button with
 * its price and cap. A press only opens the question. His «Da, aprob și cumpăr», with his note,
 * decides the approval the step raised, which the backend binds to this sheet's hash, and only then
 * is the step posted again and bought (approveStep). A stale sheet, an open BLOCK or a short
 * balance is the backend's 409, shown in its own words.
 *
 * DRAWER_COMPLETE (2026-10-01) finishes it on the backend's new routes:
 * - each scene's «Refă imaginea / mișcarea / cardul» and the film's «Refă sunetul», with the redo
 *   plan the sheet carries (its credits, cap and USD), posted to POST /media/storyboards/{id}/redo
 *   under that plan's own hash through the same approval flow as the steps (approveRedo);
 * - «Asamblează filmul» after the motion step, priced as 0 Runway credits plus the narration's
 *   cents, posted to POST .../steps/assemble under the sheet's hash (approveAssemble), with the QC
 *   verdict, its reasons and the Owner's QC letter when the film comes back;
 * - his paid-media rule as a real control (owner_controls.js paidMediaFormHtml);
 * - the SAFETY suggestion of a scene, its shot size (prompt_json.shot_size), each shot's clip QC,
 *   the premium reference, the allowed set and the narration line.
 *
 * This module is pure (no DOM, no fetch): main.js paints its HTML and passes its api().
 */

/** The drawer's name. */
export const SHEET_TITLE = 'Foaia de filmare';

/** The three paid steps, in the order they are bought (backend SHEET_STEPS). */
export const SHEET_STEPS = /** @type {const} */ (['stills', 'test_shot', 'motion']);

/** The last step: the film from its takes (backend ASSEMBLE_STEP). */
export const ASSEMBLE_STEP = 'assemble';

/** What can be redone alone (backend REDO_KINDS): a scene's still, motion or card, or the sound. */
export const REDO_KINDS = /** @type {const} */ (['still', 'motion', 'card', 'audio']);

/** The redos that buy something, and so need the Owner's yes for their plan. */
const PAID_REDOS = ['still', 'motion'];

/** Each redo's button. */
const REDO_LABELS = { still: 'Refă imaginea', motion: 'Refă mișcarea', card: 'Refă cardul', audio: 'Refă sunetul' };

/** What a redo redoes, for its question. @param {string} kind @param {number|null} scene */
function redoWhat(kind, scene) {
  if (kind === 'audio') return 'sunetul filmului';
  const what = { still: 'imaginea', motion: 'mișcarea', card: 'cardul' }[kind] || kind;
  return `${what} scenei ${scene}`;
}

/** A paid step by its word in a sentence. */
const STEP_WORDS = { stills: 'imaginile', test_shot: 'cadrul de probă', motion: 'mișcarea' };

/** Each step's button. */
const STEP_LABELS = {
  stills: 'Aprobă imaginile',
  test_shot: 'Aprobă cadrul de probă',
  motion: 'Aprobă mișcarea',
};

/** Each step's question, when the Owner pressed its button. */
const STEP_QUESTIONS = {
  stills: 'Cumperi imaginile scenelor filmate?',
  test_shot: 'Cumperi cadrul de probă? El rămâne în film.',
  motion: 'Cumperi mișcarea pentru restul scenelor?',
};

/**
 * How long the page waits for a paid step (ms). The backend buys every still or clip of the step
 * before it answers, polling the vendor for each, so the page's usual 10 s would abort a purchase
 * that is still running on the server.
 */
export const STEP_TIMEOUT_MS = 45 * 60 * 1000;

/** The margin over a step's next round the Runway balance must hold to start it (backend balance_rule). */
const BALANCE_MARGIN = 1.15;

/** A scene composed locally, by kind: the word the backend's price line uses. */
const COMPOSED_WORDS = { DATA_CARD: 'Grafic', TITLE_CARD: 'Titlu', BLACK: 'Ecran negru' };

/** How a composed scene is made, said under it. */
const COMPOSED_WHY = {
  DATA_CARD: 'Se compune local din cifrele verificate; nu ajunge la niciun generator plătit.',
  TITLE_CARD: 'Se compune local din textul scenei; nu ajunge la niciun generator plătit.',
  BLACK: 'Ecran negru compus local; nu ajunge la niciun generator plătit.',
};

/** What a take's status means on the contact sheet. */
const TAKE_WORDS = {
  QUOTED: 'Doar cotată, necumpărată',
  PAID: 'Cumpărată, neaprobată încă',
  APPROVED: 'Aprobată',
  REJECTED: 'Respinsă',
  REFUSED: 'Refuzată de furnizor',
  // never collected before the vendor's output expired (assembler's LOST, VENDOR.NOT_COLLECTED)
  LOST: 'Pierdută: rezultatul nu a mai putut fi ridicat de la furnizor',
};

/**
 * A take still at the vendor, by its status (the take's, or its RunPod job's), with the vendor
 * named: «Trimisă la RunPod: se generează». 2026-10-09: «Alte imagini» showed «SUBMITTED».
 * @type {Record<string, (vendor: string) => string>}
 */
const IN_FLIGHT_WORDS = {
  STARTING: (v) => `Se trimite la ${v}`,
  SUBMITTED: (v) => `Trimisă la ${v}: se generează`,
  QUEUED: (v) => `La coadă la ${v}: așteaptă un GPU`,
  IN_QUEUE: (v) => `La coadă la ${v}: așteaptă un GPU`,
  RUNNING: (v) => `Trimisă la ${v}: se generează`,
  IN_PROGRESS: (v) => `Trimisă la ${v}: se generează`,
  UPLOADING: (v) => `Gata la ${v}: se aduce în studio`,
};

/**
 * A take's status in the Owner's words, never the raw code (which stays in `data-status`).
 * `vendor` is «RunPod» on a film bought on RunPod's GPU (`gpuBilled`), else «furnizor».
 * @param {unknown} status @param {string} [vendor]
 */
export function takeStatusWords(status, vendor = 'furnizor') {
  const key = String(status ?? '');
  const settled = /** @type {Record<string, string>} */ (TAKE_WORDS)[key];
  if (settled) return settled;
  const sent = IN_FLIGHT_WORDS[key];
  return sent ? sent(vendor) : 'Stare necunoscută';
}

const NUMBER = new Intl.NumberFormat('ro-RO', { useGrouping: true, maximumFractionDigits: 2 });
const MONEY = new Intl.NumberFormat('ro-RO', { useGrouping: true, minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * A count in Romanian: «1 credit», «18 credite», «340 de credite», «1.284 de credite». A number
 * the backend did not send is «necunoscut», never 0.
 * @param {unknown} value @param {string} [one] @param {string} [many]
 */
export function countWords(value, one = 'credit', many = 'credite') {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return 'necunoscut';
  const n = Number(value);
  if (n === 1) return `1 ${one}`;
  if (!Number.isInteger(n)) return `${NUMBER.format(n)} ${many}`;
  const rest = Math.abs(n) % 100;
  const joiner = Math.abs(n) >= 20 && (rest === 0 || rest >= 20) ? ' de ' : ' ';
  return `${NUMBER.format(n)}${joiner}${many}`;
}

/** Credits in Romanian. @param {unknown} value */
export function creditWords(value) {
  return countWords(value);
}

/** USD micros as «3,40 USD»; «necunoscut» when not sent. @param {unknown} micros */
export function usdText(micros) {
  if (micros === null || micros === undefined || !Number.isFinite(Number(micros))) return 'necunoscut';
  return `${MONEY.format(Number(micros) / 1e6)} USD`;
}

/** USD as a decimal number (the step's cost_usd) to micros. @param {unknown} usd */
function micros(usd) {
  return usd === null || usd === undefined || !Number.isFinite(Number(usd)) ? null : Math.round(Number(usd) * 1e6);
}

/** A value on a card, the Romanian way («83», «83,5», «1.000»). @param {unknown} value */
function cardValue(value) {
  const n = Number(value);
  return Number.isFinite(n) ? new Intl.NumberFormat('ro-RO', { useGrouping: true, maximumFractionDigits: 6 }).format(n) : String(value ?? '');
}

/**
 * The shot sizes the prompt compilers write into prompt_json.shot_size (prompt_agent.shot_frame for
 * a factual film, series_look for the office serial), in the Owner's words.
 */
const SHOT_SIZE_WORDS = {
  aerial: 'Plan aerian',
  wide: 'Plan larg',
  medium: 'Plan mediu',
  close: 'Prim-plan',
  detail: 'Detaliu',
  establishing: 'Plan de ansamblu',
  two_shot: 'Plan mediu în doi',
  single: 'Plan apropiat',
};

/** A shot size in words; '' for none or one the compilers do not write. @param {unknown} size */
export function shotSizeWord(size) {
  const key = String(size || '').trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(SHOT_SIZE_WORDS, key) ? SHOT_SIZE_WORDS[/** @type {keyof typeof SHOT_SIZE_WORDS} */ (key)] : '';
}

/** For a scene written before the compiler named its size: the size its still prompt names. */
const FRAME_WORDS = /** @type {const} */ ([
  [/\b(detail|details|close-up|close up|closeup|macro|hands)\b/i, 'Detaliu'],
  [/\bmedium\b/i, 'Plan mediu'],
  [/\b(wide|establishing|aerial|landscape|panorama|vista)\b/i, 'Plan larg'],
]);

/**
 * What the camera frames in a scene, in one word: its prompt_json.shot_size, else the shot size
 * its still prompt names (the earliest one wins), or the card's kind. Words only: nothing is
 * decided from it.
 * @param {any} scene a sheet scene
 */
export function frameWord(scene) {
  const kind = String(scene?.kind || 'LIVE');
  if (kind in COMPOSED_WORDS) return COMPOSED_WORDS[/** @type {keyof typeof COMPOSED_WORDS} */ (kind)];
  const sized = shotSizeWord(scene?.shot_size);
  if (sized) return sized;
  const text = String(scene?.still_prompt || '');
  let best = { at: Infinity, word: 'Cadru filmat' };
  for (const [pattern, word] of FRAME_WORDS) {
    const found = pattern.exec(text);
    if (found && found.index < best.at) best = { at: found.index, word };
  }
  return best.word;
}

/** @param {any} scene */
function isCard(scene) {
  return String(scene?.kind || 'LIVE') in COMPOSED_WORDS;
}

/** A file from the current prompt, rather than a submitted or refused request. @param {any} scene */
export function sceneMediaState(scene) {
  if (isCard(scene)) return { label: 'Grafic local', tone: 'quiet', generated: false, take: null };
  if (scene?.motion?.status === 'LOCAL') return { label: 'Animație locală aleasă', tone: 'quiet', generated: false, take: null };
  const shots = (Array.isArray(scene?.shots) ? scene.shots : []).filter((/** @type {any} */ s) => s.for_current_prompt !== false);
  const files = shots.filter((/** @type {any} */ s) => s.file_url && ['PAID', 'APPROVED'].includes(s.status));
  const take = files.find((/** @type {any} */ s) => s.status === 'APPROVED') || files[0];
  if (take) return { label: take.status === 'APPROVED' ? 'Clip aprobat' : 'Clip generat, de verificat', tone: take.status === 'APPROVED' ? 'ok' : 'info', generated: true, take };
  if (shots.some((/** @type {any} */ s) => s.status === 'SUBMITTED')) return { label: 'Cerere trimisă, fără clip încă', tone: 'info', generated: false, take: null };
  if (shots.some((/** @type {any} */ s) => s.status === 'REFUSED')) return { label: 'Refuzat, fără clip', tone: 'alert', generated: false, take: null };
  if (shots.some((/** @type {any} */ s) => s.status === 'REJECTED')) return { label: 'Clip respins', tone: 'warn', generated: false, take: null };
  return { label: 'Clip negenerat', tone: 'quiet', generated: false, take: null };
}

/** Counts only the sheet's chosen images and current usable clip files. @param {any} sheet */
export function sheetProgress(sheet) {
  const scenes = Array.isArray(sheet?.scenes) ? sheet.scenes : [];
  const filmed = scenes.filter((/** @type {any} */ s) => !isCard(s));
  return {
    filmed: filmed.length,
    images: filmed.filter((/** @type {any} */ s) => s.still?.take_id && s.still?.approved_by).length,
    clips: filmed.filter((/** @type {any} */ s) => sceneMediaState(s).generated).length,
    local: filmed.filter((/** @type {any} */ s) => s.motion?.status === 'LOCAL').length,
    cards: scenes.length - filmed.length,
  };
}

/** The backend's held hero can be retried through its existing, priced redo. @param {any} sheet */
export function testShotRecovery(sheet) {
  const hero = sheet?.footer?.hero_scene;
  if (hero === null || hero === undefined) return null;
  const scene = (Array.isArray(sheet?.scenes) ? sheet.scenes : []).find((/** @type {any} */ s) => Number(s.scene_index) === Number(hero));
  const held = (sheet?.steps?.test_shot?.held || []).includes(Number(hero)) || scene?.motion?.step_status === 'NEEDS_OWNER';
  if (!scene || !held || sceneMediaState(scene).generated || scene.motion?.status === 'LOCAL') return null;
  return redoButtons(scene).find((b) => b.kind === 'motion') || null;
}

/**
 * One scene in one line: «Cadrul 3 · Peisaj · seedance2_5 · 1080p · 5 s · 340 de credite». A card
 * reads «Cadrul 5 · Grafic compus local · 0 credite»; a scene with no model says so.
 * @param {any} scene a sheet scene
 */
export function sceneLine(scene) {
  const head = `Cadrul ${scene?.scene_index ?? '?'}`;
  if (isCard(scene)) return `${head} · ${frameWord(scene)} compus local · 0 credite`;
  const m = scene?.motion || {};
  const frame = `${head} · ${frameWord(scene)}`;
  if (m.status === 'LOCAL') return `${frame} · imagine fixă animată local · 0 credite`;
  if (!m.model_id) return `${frame} · fără model ales: ${String(m.reason_ro || 'decide Proprietarul.')}`;
  const resolution = m.local_generation ? `${m.native_resolution || '—'} nativ → montaj ${m.resolution}` : (m.resolution || '—');
  return `${frame} · ${m.model_id} · ${resolution} · ${m.billed_seconds ?? '?'} s · ${m.local_generation ? 'cost API zero' : creditWords(m.credits)}`;
}

/**
 * The prompt lint of a scene in words: «curat», or «2 blocaje, 1 avertisment».
 * @param {any} scene
 */
export function lintLine(scene) {
  const findings = Array.isArray(scene?.lint) ? scene.lint : [];
  const blocks = findings.filter((/** @type {any} */ f) => f && f.severity === 'BLOCK').length;
  const warns = findings.filter((/** @type {any} */ f) => f && f.severity === 'WARN').length;
  const parts = [];
  if (blocks) parts.push(countWords(blocks, 'blocaj', 'blocaje'));
  if (warns) parts.push(countWords(warns, 'avertisment', 'avertismente'));
  return parts.join(', ') || 'curat';
}

/** «1 întrebare veche retrasă», «2 întrebări vechi retrase». @param {number} n */
export function withdrawnWords(n) {
  return countWords(n, 'întrebare veche retrasă', 'întrebări vechi retrase');
}

/**
 * A shot's clip QC (the report kept on its take, backend assembler.clip_qc_of), in one line.
 * @param {any} record
 */
export function clipQcWords(record) {
  if (!record || typeof record !== 'object') return 'Controlul clipului: nerulat încă.';
  const blocks = (Array.isArray(record.blocks_ro) ? record.blocks_ro : []).map((/** @type {unknown} */ b) => String(b).trim().replace(/\.$/, '')).filter(Boolean).join('; ');
  if (record.verdict === 'PASSED') return 'Controlul clipului: trecut.';
  if (record.verdict === 'FAILED') return blocks ? `Controlul clipului: picat — ${blocks}.` : 'Controlul clipului: picat.';
  return `Controlul clipului: neverificat${blocks ? ` (${blocks})` : ''} — așteaptă privirea ta.`;
}

/* ------------------------------------------------------------------------------- the redos */

/**
 * @typedef {{kind: string, scene: number|null, label: string, price_ro: string, cap_ro: string,
 *   free: boolean, plan_hash: string|null, disabled: boolean, reason_ro: string, cap_usd: number,
 *   replaces: string[], invalidates: string[], round_credits: number}} RedoButton
 */

/** @param {string} kind @param {any} plan @param {number|null} scene @returns {RedoButton} */
function redoButton(kind, plan, scene) {
  const p = plan && typeof plan === 'object' ? plan : { available: false, reason_ro: 'Planul refacerii nu a fost citit.' };
  const free = p.free === true;
  const hash = typeof p.plan_hash === 'string' && /^[0-9a-f]{64}$/.test(p.plan_hash) ? p.plan_hash : null;
  const disabled = p.available === false || (!free && (!hash || p.buyable === false));
  return {
    kind,
    scene,
    label: REDO_LABELS[/** @type {keyof typeof REDO_LABELS} */ (kind)],
    price_ro: free ? '0 credite' : `${creditWords(p.credits ?? 0)} (${usdText(micros(p.cost_usd ?? 0))})`,
    cap_ro: free ? '' : `plafon ${creditWords(p.cap_credits ?? 0)} (${usdText(micros(p.cap_usd ?? 0))})`,
    free,
    plan_hash: hash,
    disabled,
    reason_ro: String(p.reason_ro || ''),
    cap_usd: Number(p.cap_usd) || 0,
    round_credits: Number(p.credits) || 0,
    replaces: Array.isArray(p.replaces) ? p.replaces.map(String) : [],
    invalidates: Array.isArray(p.invalidates) ? p.invalidates.map(String) : [],
  };
}

/**
 * A scene's «Refă» buttons, from the redo plans the sheet carries: the still and the motion of a
 * filmed scene, the card of a composed one. Each has the plan's price and cap and its hash.
 * @param {any} scene
 * @returns {RedoButton[]}
 */
export function redoButtons(scene) {
  const plans = scene?.redo && typeof scene.redo === 'object' ? scene.redo : {};
  const index = Number(scene?.scene_index);
  return ['still', 'motion', 'card'].filter((kind) => kind in plans).map((kind) => redoButton(kind, plans[kind], index));
}

/** The film's «Refă sunetul»; null when the sheet has no such plan. @param {any} sheet */
export function audioRedoButton(sheet) {
  const plan = sheet?.footer?.audio_redo;
  return plan ? redoButton('audio', plan, null) : null;
}

/** The key of a redo's question in the drawer. @param {string} kind @param {number|string|null} scene */
export function redoKey(kind, scene) {
  return `redo:${kind}:${scene ?? ''}`;
}

/** @param {string|null|undefined} key @returns {{kind: string, scene: number|null}|null} */
function parseRedoKey(key) {
  const found = /^redo:(still|motion|card|audio):(\d*)$/.exec(String(key || ''));
  if (!found) return null;
  return { kind: found[1], scene: found[2] ? Number(found[2]) : null };
}

/** The button a redo key names on this sheet. @param {any} sheet @param {string|null|undefined} key */
function redoFor(sheet, key) {
  const parsed = parseRedoKey(key);
  if (!parsed) return null;
  if (parsed.kind === 'audio') return audioRedoButton(sheet);
  const scene = (Array.isArray(sheet?.scenes) ? sheet.scenes : []).find((/** @type {any} */ s) => s && Number(s.scene_index) === parsed.scene);
  return scene ? redoButtons(scene).find((b) => b.kind === parsed.kind) || null : null;
}

/** Whether a cap in USD is over what the day has left. @param {any} sheet @param {number} capUsd */
function overDailyBudget(sheet, capUsd) {
  const daily = sheet?.footer?.daily_budget;
  return Boolean(daily && Number.isFinite(capUsd) && capUsd > 0 && Number.isFinite(Number(daily.remaining_usd)) && capUsd > Number(daily.remaining_usd));
}

/**
 * The hero test shot: which scene, whether it was bought and whether the Owner approved it.
 * @param {any} sheet
 * @returns {{scene: number|null, bought: boolean, approved: boolean, take: any}}
 */
export function heroState(sheet) {
  const index = sheet?.footer?.hero_scene;
  if (index === null || index === undefined) return { scene: null, bought: false, approved: false, take: null };
  const scene = (Array.isArray(sheet?.scenes) ? sheet.scenes : []).find((/** @type {any} */ s) => s && s.scene_index === index);
  const shots = Array.isArray(scene?.shots) ? scene.shots : [];
  const m = scene?.motion || {};
  const take = shots.find((/** @type {any} */ s) => s && s.take_id === m.take_id) || shots.find((/** @type {any} */ s) => s && s.kind === 'test_shot') || null;
  const status = m.take_status || take?.status || null;
  return {
    scene: Number(index),
    bought: m.status === 'BOUGHT' || status === 'PAID' || status === 'APPROVED',
    approved: status === 'APPROVED',
    take,
  };
}

/** The hero gate's answers that let the rest of the motion be bought (backend assembler.hero_gate). */
const HERO_LETS_MOTION = ['NO_HERO', 'APPROVED', 'ACCEPTED', 'ACCEPTS'];

/**
 * Why nothing can be pressed while the film is being bought elsewhere (GATES_BEFORE_BUYING's
 * per-film lease, `sheet.in_progress`), in the backend's words; '' when nothing is.
 * @param {any} sheet
 */
function inProgressReason(sheet) {
  const lease = sheet?.in_progress;
  if (!lease || typeof lease !== 'object') return '';
  return String(lease.reason_ro || 'Filmul este deja în lucru: o cumpărare a lui nu s-a încheiat încă.');
}

/**
 * SHEET_BUSY_ONCE: the busy sentence is said once on the sheet, in the sticky bar at the top (it
 * is there whether he pressed or not, and its minutes are read again on every repaint). Each step
 * below points to it in these few words instead of repeating it.
 */
export const BUSY_SEE_BAR = 'Filmul este deja în lucru (vezi bara de sus).';

/**
 * Whether a «Refă» must wait for the film's lease: a still or motion redo buys under the film's
 * one purchase lease (backend redo_scene), so while `sheet.in_progress` stands it would only be
 * refused FILM_BUSY after his yes had been decided. A card or the sound takes no lease.
 * @param {any} sheet @param {RedoButton} b
 */
function redoWaitsForLease(sheet, b) {
  return PAID_REDOS.includes(b.kind) && Boolean(inProgressReason(sheet));
}

/** What the status line says when his press was refused because the film is at work (FILM_BUSY). */
export const BUSY_PRESS_WORDS = 'Apăsarea ta nu a pornit nimic: filmul este deja în lucru, iar bara de sus spune de când. Apasă din nou după ce pasul în curs se termină.';

/**
 * The drawer's status line for a notice: a press refused FILM_BUSY while the sheet's bar already
 * says the film is at work is answered with a pointer to the bar (a wait, not a failure), so the
 * sentence is not shown twice. If the lease ended before the sheet was read again, the bar says
 * nothing and the line keeps the backend's sentence.
 * @param {string} notice @param {string|null|undefined} code @param {boolean} failed @param {any} sheet
 * @returns {{text: string, tone: 'ok'|'error'|'waiting'}}
 */
export function sheetStatusText(notice, code, failed, sheet) {
  const text = String(notice || '');
  if (failed && code === 'FILM_BUSY' && inProgressReason(sheet)) return { text: BUSY_PRESS_WORDS, tone: 'waiting' };
  return { text, tone: text && failed ? 'error' : 'ok' };
}

/*
 * «ÎNCHIDE FILMUL» (2026-10-09). Three old films each waited for his look at one scene, and the day
 * chose no new topic while any of them stood. The backend's `sheet.closure` (film_close.py
 * closure_view) says whether the film is closed, or can be closed now and why not; the first press
 * of «Închide filmul» only opens «Confirmă închiderea filmului» with what closing does, and the
 * confirmation posts POST /media/storyboards/{id}/close once (closeFilm). A closed film's paid
 * buttons say it is closed; the backend refuses them anyway (409 FILM_CLOSED).
 */

/** The drawer's confirm key for the close (`sheetDrawer.confirm`), as a step's name is for a step. */
export const CLOSE_FILM = 'close-film';

/** What closing does, said on its confirmation; the backend's answer says it again with figures. */
export const CLOSE_FILM_EFFECTS = /** @type {const} */ ([
  'Nimic nu se mai cumpără pentru el.',
  'Ce s-a cumpărat rămâne în registre.',
  'Subiectul nu mai ține studioul pe loc: rularea următoare alege alt subiect.',
]);

/**
 * The confirmation's three effects: the third is what the backend read about the film's topic
 * (`closure.topic_ro`: a newer film of the same topic may still hold the studio), the default
 * only for an older studio that does not say it. @param {any} closure @returns {string[]}
 */
export function closeFilmEffects(closure) {
  const topic = typeof closure?.topic_ro === 'string' && closure.topic_ro.trim() ? closure.topic_ro.trim() : '';
  return [CLOSE_FILM_EFFECTS[0], CLOSE_FILM_EFFECTS[1], topic || CLOSE_FILM_EFFECTS[2]];
}

/** Why a closed film's paid buttons cannot be pressed; '' while the film is not closed. @param {any} sheet */
function closedReason(sheet) {
  const closure = sheet?.closure;
  if (!closure || typeof closure !== 'object' || !closure.closed) return '';
  return 'Filmul este închis: pentru el nu se mai cumpără nimic.';
}

/** @param {string} storyboardId */
export function closeFilmPath(storyboardId) {
  return `/media/storyboards/${storyboardId}/close`;
}

/** @param {string} commandId @returns {{schema_version: 1, command_id: string}} */
export function closeFilmCommand(commandId) {
  return { schema_version: 1, command_id: commandId };
}

/** «Închis de tine, pe 9 oct. 2026, 13:00.» @param {any} closure */
function closedByWords(closure) {
  const by = closure?.closed_by === 'Owner' ? 'de tine' : closure?.closed_by === 'Director' ? 'de Directoare' : '';
  const at = new Date(String(closure?.closed_at || ''));
  const when = Number.isNaN(at.getTime()) ? '' : `, pe ${at.toLocaleString('ro-RO', { dateStyle: 'medium', timeStyle: 'short' })}`;
  return by ? `Închis ${by}${when}.` : '';
}

/**
 * The close on the sheet: the closed film's words, or «Închide filmul» (disabled with the reason
 * it cannot close now), or, once armed (`o.confirm === CLOSE_FILM`), its confirmation. '' for an
 * older studio that sends no `closure`.
 * @param {any} sheet @param {SheetOptions} o
 */
export function closeFilmHtml(sheet, o) {
  const closure = sheet?.closure;
  if (!closure || typeof closure !== 'object') return '';
  const e = o.escape;
  if (closure.closed) {
    const by = closedByWords(closure);
    return '<section class="sheet-close sheet-close-closed" aria-label="Filmul este închis">'
      + '<h2>Filmul este închis</h2>'
      + `<p>${e(String(closure.words_ro || 'Pentru el nu se mai cumpără nimic; ce s-a cumpărat rămâne în registre.'))}</p>`
      + (by ? `<p class="sheet-close-meta">${e(by)}</p>` : '')
      + '</section>';
  }
  const busy = inProgressReason(sheet);
  const reason = closure.closable === false
    ? String(closure.reason_ro || 'Filmul nu se poate închide de aici.')
    : busy ? BUSY_SEE_BAR : '';
  if (o.confirm === CLOSE_FILM && !reason) {
    const title = String(sheet?.title || '').replace(/^Storyboard:\s*/i, '');
    return '<section class="sheet-close" aria-label="Închide filmul">'
      + '<div class="sheet-confirm" role="group" aria-label="Confirmă închiderea filmului">'
      + `<p class="sheet-confirm-q">Închizi filmul${title ? ` «${e(title)}»` : ''}?</p>`
      + `<ul class="sheet-close-effects">${closeFilmEffects(closure).map((effect) => `<li>${e(effect)}</li>`).join('')}</ul>`
      + '<div class="sheet-confirm-actions">'
      + '<button type="button" class="sheet-yes sheet-close-yes" data-sheet-action="confirm-close-film">Confirmă închiderea filmului</button>'
      + '<button type="button" class="quiet" data-sheet-action="cancel-step">Nu acum</button>'
      + '</div></div></section>';
  }
  return '<section class="sheet-close" aria-label="Închide filmul">'
    + '<div class="sheet-section-heading"><h2>Închide filmul</h2><p>Dacă nu mai vrei acest film: nu se mai cumpără nimic pentru el și nu ți se mai cere nimic despre el.</p></div>'
    + `<button type="button" class="quiet sheet-close-btn" data-sheet-action="close-film"${reason ? ' disabled' : ''}>Închide filmul</button>`
    + (reason ? `<p class="sheet-close-why">${e(reason)}</p>` : '')
    + '</section>';
}

/**
 * The Owner's «Confirmă închiderea filmului»: one POST with its own command id (the same press sent
 * again answers what it did). A refusal (409: a purchase in flight, a rendered film, a serial
 * episode) comes back in the backend's own words.
 * @param {(path: string, options?: any) => Promise<any>} api
 * @param {{storyboardId: string, commandId: string}} o
 * @returns {Promise<{status: 'CLOSED', message: string, result: any} | {status: 'REFUSED', code: string|null, message: string, scenes: string[]}>}
 */
export async function closeFilm(api, o) {
  try {
    const result = await api(closeFilmPath(o.storyboardId), { method: 'POST', body: JSON.stringify(closeFilmCommand(o.commandId)) });
    return { status: 'CLOSED', message: String(result?.words_ro || 'Filmul este închis.'), result };
  } catch (error) {
    if (error && /** @type {any} */ (error).network) {
      return { status: 'REFUSED', code: 'NETWORK', message: 'Răspunsul nu a ajuns; filmul poate fi închis deja. Reîncarcă foaia înainte de a apăsa din nou.', scenes: [] };
    }
    return refused(error);
  }
}

/**
 * The step buttons: label, price and cap, and every Romanian reason it cannot be pressed now.
 * @param {any} sheet
 * @returns {{step: string, label: string, price_ro: string, cap_ro: string, to_buy: number[], disabled: boolean, reasons: string[], reason_ro: string, over_budget: boolean, over_budget_ro: string}[]}
 */
export function stepButtons(sheet) {
  const footer = sheet?.footer || {};
  const gaps = Array.isArray(sheet?.shot_plan_gaps) ? sheet.shot_plan_gaps : [];
  const hero = heroState(sheet);
  const busy = inProgressReason(sheet);
  return SHEET_STEPS.map((name) => {
    const step = (sheet?.steps && sheet.steps[name]) || {};
    const toBuy = Array.isArray(step.to_buy) ? step.to_buy.map(Number) : [];
    const cap = Number(step.cap_credits) || 0;
    /** @type {string[]} */
    const reasons = [];
    // «Închide filmul»: a closed film buys nothing more (the backend answers 409 FILM_CLOSED).
    const closed = closedReason(sheet);
    if (closed) reasons.push(closed);
    // PAGE-06: a purchase of this film is running (the day, or another press): nothing is
    // pressed until it ends; the backend would answer 409 FILM_BUSY anyway.
    if (busy) reasons.push(busy);
    else if (step.in_progress) reasons.push(`Pasul «${STEP_WORDS[/** @type {keyof typeof STEP_WORDS} */ (name)]}» este deja în curs; foaia se reîncarcă singură când se termină.`);
    if (sheet?.lint_blocked) reasons.push(`Blocaj deschis: ${sheet.lint_summary_ro || 'prompturile au blocaje.'}`);
    if (gaps.length) reasons.push(`Scenele ${gaps.join(', ')} nu au planul de cadre scris de model; filmul așteaptă planul de cadre.`);
    if (!toBuy.length) reasons.push(String(step.waiting_ro || 'Nu este nimic de cumpărat la acest pas.'));
    if (name === 'motion' && hero.scene !== null && !hero.approved) {
      // HERO_AUTO_ACCEPT: the backend's own gate says whether the hero lets the motion follow
      // (clip QC under his rule, or his look); an older backend sends none, and the page then
      // asks for his look as it always did.
      const gate = step.hero && typeof step.hero === 'object' ? step.hero : null;
      if (gate && typeof gate.status === 'string') {
        if (!HERO_LETS_MOTION.includes(gate.status)) {
          reasons.push(String(gate.reason_ro || `Cadrul de probă (scena ${hero.scene}) așteaptă privirea ta.`));
        }
      } else {
        reasons.push(hero.bought
          ? `Cadrul de probă (scena ${hero.scene}) așteaptă privirea ta: aprobă-l pe foaie înainte de restul mișcării.`
          : `Întâi cadrul de probă (scena ${hero.scene}): restul mișcării se cumpără abia după ce îl vezi și îl aprobi.`);
      }
    }
    if (toBuy.length) {
      const balance = footer.balance || {};
      // The Owner's rule of 2026-10-03: a step starts on its next round × the margin (the
      // backend's balance_needed_credits); its cap stays the ceiling and is named beside it.
      const round = Number(step.cost_credits) || 0;
      const neededRaw = footer.balance_needed_credits ? footer.balance_needed_credits[name] : undefined;
      const needed = Number.isFinite(Number(neededRaw)) && neededRaw !== null ? Number(neededRaw) : Math.ceil(Math.round(round * BALANCE_MARGIN * 1e6) / 1e6);
      if (balance.applicable === false && (cap === 0 || balance.billing_mode === 'gpu')) {
        // Local/GPU generation uses its own pricing; the approved cap and daily budget remain.
      } else if (balance.credits === null || balance.credits === undefined || !Number.isFinite(Number(balance.credits))) {
        reasons.push(`Soldul Runway nu a putut fi citit (${balance.problem || 'necunoscut'}); nimic nu se cumpără pe un sold necunoscut.`);
      } else if (Number(balance.credits) < needed) {
        reasons.push(`Sold Runway insuficient: ${creditWords(Number(balance.credits))}; runda următoare a pasului costă ${creditWords(round)}, cu marja de 15% ${creditWords(needed)}. Plafonul aprobat rămâne ${creditWords(cap)}.`);
      }
    }
    const daily = footer.daily_budget;
    const capUsd = Number(step.cap_usd);
    const overBudget = Boolean(toBuy.length && daily && Number.isFinite(capUsd) && Number.isFinite(Number(daily.remaining_usd)) && capUsd > Number(daily.remaining_usd));
    return {
      step: name,
      label: STEP_LABELS[name],
      // RunPod Serverless: a round's GPU start (cold start + idle tail) is inside the price.
      price_ro: `${creditWords(step.cost_credits ?? 0)} (${usdText(micros(step.cost_usd ?? 0))})`
        + (Number(step.gpu_start_credits) > 0 && step.gpu_start_ro ? `, cu ${String(step.gpu_start_ro)}` : ''),
      cap_ro: `plafon ${creditWords(cap)} (${usdText(micros(step.cap_usd ?? 0))})`,
      to_buy: toBuy,
      disabled: reasons.length > 0,
      reasons,
      reason_ro: reasons.join(' '),
      over_budget: overBudget,
      over_budget_ro: overBudget
        ? `Bugetul zilei: plafonul pasului (${usdText(micros(capUsd))}) depășește ce a rămas azi (${usdText(micros(daily.remaining_usd))}).`
        : '',
    };
  });
}

/**
 * The assembly's button: after the paid steps, priced as 0 Runway credits and the narration's
 * cents (the backend's own figure), held by every scene the backend says has no accepted take.
 * @param {any} sheet
 * @returns {{label: string, price_ro: string, line_ro: string, disabled: boolean, reasons: string[], reason_ro: string}}
 */
export function assembleButton(sheet) {
  const step = sheet?.steps?.[ASSEMBLE_STEP];
  const label = 'Asamblează filmul';
  if (!step || typeof step !== 'object') {
    const reason = 'Studioul nu are încă pasul de asamblare pe foaie; el apare după repornirea studioului.';
    return { label, price_ro: '0 credite Runway', line_ro: '', disabled: true, reasons: [reason], reason_ro: reason };
  }
  const narration = step.narration || sheet?.footer?.narration || {};
  let voice = `narațiunea ${usdText(narration.usd_micros)}`;
  if (Number(narration.characters) === 0) voice = 'fără narațiune';
  else if (narration.priced === false) voice = 'narațiunea: preț necunoscut, te întreabă înainte';
  /** @type {string[]} */
  const reasons = [];
  const closed = closedReason(sheet);
  if (closed) reasons.push(closed);
  const busy = inProgressReason(sheet);
  if (busy) reasons.push(busy);
  else if (step.in_progress) reasons.push('Asamblarea este deja în curs; foaia se reîncarcă singură când se termină.');
  const left = (Array.isArray(step.paid_steps_left) ? step.paid_steps_left : []).map((/** @type {string} */ s) => STEP_WORDS[/** @type {keyof typeof STEP_WORDS} */ (s)] || s);
  if (left.length) reasons.push(`Întâi pașii plătiți rămași: ${left.join(', ')}. Filmul se asamblează după ultimul.`);
  // TAKE_CHOICE_SEEN (2026-10-04): the backend groups the scenes the assembly waits for into one
  // sentence per reason (`blocked_ro`, «Scenele 1, 2, 3, 4 și 6 …»); an older studio sent only
  // one sentence per scene, said here as before.
  if (step.blocked_ro) reasons.push(String(step.blocked_ro));
  else for (const b of Array.isArray(step.blocked) ? step.blocked : []) if (b && b.reason_ro) reasons.push(String(b.reason_ro));
  if (step.ready === false && !reasons.length) reasons.push(String(step.waiting_ro || 'Filmul nu poate fi asamblat încă.'));
  return {
    label,
    price_ro: `0 credite Runway · ${voice}`,
    line_ro: String(narration.line_ro || ''),
    disabled: reasons.length > 0,
    reasons,
    reason_ro: reasons.join(' '),
  };
}

/**
 * The film's own ceiling (GATES_BEFORE_BUYING, `footer.film_budget`): what the film already holds
 * against it and what is left. None from an older studio.
 * @param {any} budget
 * @returns {{key: string, label: string, value: string}[]}
 */
function filmBudgetRows(budget) {
  if (!budget || typeof budget !== 'object') return [];
  return [{
    key: 'film_budget',
    label: 'Plafonul filmului',
    value: `${usdText(budget.spent_usd_micros)} cheltuiți din ${usdText(budget.limit_usd_micros)}; rămân ${usdText(budget.remaining_usd_micros)}`,
  }];
}

/**
 * The footer, worded from the backend's figures (never recomputed).
 * @param {any} sheet
 * @returns {{key: string, label: string, value: string}[]}
 */
export function footerRows(sheet) {
  const f = sheet?.footer || {};
  const money = (/** @type {unknown} */ credits, /** @type {unknown} */ usdMicros) => `${creditWords(credits)} (${usdText(usdMicros)})`;
  const spent = f.stills_spent_credits || {};
  let stillsSpent = '0 credite';
  if (spent.measured_credits !== null && spent.measured_credits !== undefined) stillsSpent = `${creditWords(spent.measured_credits)} (măsurat)`;
  else if (Number(spent.quoted_credits) > 0) stillsSpent = `${creditWords(spent.quoted_credits)} (estimat, nemăsurat)`;
  const balance = f.balance || {};
  const daily = f.daily_budget;
  const premium = f.premium_model_id ? `${f.premium_model_id}${f.premium_resolution ? ` la ${f.premium_resolution}` : ''}` : 'seedance2_5';
  const alternatives = (Array.isArray(f.alternatives) ? f.alternatives : []).map((/** @type {any} */ a) => {
    const name = a.model_id === 'mixt' ? `același film la ${a.resolution}` : `${a.model_id} ${a.resolution}`;
    return `${name}: ${money(a.total_credits, a.total_usd_micros)}${a.price_source ? ` · ${a.price_source}` : ''}`;
  });
  return [
    { key: 'stills_spent', label: 'Imagini deja plătite', value: stillsSpent },
    { key: 'stills_to_buy', label: 'Imagini de cumpărat', value: money(f.stills_to_buy_credits ?? 0, f.stills_to_buy_usd_micros ?? 0) },
    {
      key: 'hero',
      label: 'Cadrul de probă',
      value: f.hero_scene === null || f.hero_scene === undefined ? 'fără cadru de probă' : `scena ${f.hero_scene} · ${money(f.hero_credits, f.hero_usd_micros)} · rămâne în film`,
    },
    { key: 'rest', label: 'Restul mișcării', value: money(f.rest_credits, f.rest_usd_micros) },
    { key: 'total', label: 'Total', value: money(f.total_credits, f.total_usd_micros) },
    { key: 'cap', label: 'Plafon ferm', value: money(f.cap_credits, f.cap_usd_micros) },
    { key: 'saved', label: 'Economie', value: `${money(f.saved_credits, f.saved_usd_micros)} față de ${premium} peste tot` },
    { key: 'source', label: 'Sursa prețurilor', value: String(f.price_source || 'necunoscută') },
    { key: 'balance', label: balance.billing_mode === 'gpu' ? 'RunPod GPU Cloud' : balance.applicable === false ? 'Generare locală' : 'Sold Runway', value: balance.billing_mode === 'gpu' ? 'Cost GPU estimat în USD · bugetul și plafonul se aplică' : balance.applicable === false ? 'Cost API zero · timpul și energia nu sunt incluse' : balance.credits === null || balance.credits === undefined ? `necitit (${balance.problem || 'necunoscut'})` : creditWords(Number(balance.credits)) },
    ...runpodCostRows(f.runpod_metrics),
    { key: 'daily', label: 'Bugetul zilei', value: daily ? `${usdText(micros(daily.remaining_usd))} rămași din ${usdText(micros(daily.limit_usd))}` : 'fără buget zilnic citit' },
    ...filmBudgetRows(f.film_budget),
    { key: 'alternatives', label: 'Alternative', value: alternatives.join('; ') || 'niciuna cu preț publicat' },
    {
      key: 'premium',
      label: 'Referința premium',
      value: f.premium_model_id
        ? `${f.premium_model_id} · ${f.premium_resolution || '—'}${Number.isFinite(Number(f.hero_threshold)) && f.hero_threshold !== null ? ` · pragul cadrului de probă ${NUMBER.format(Number(f.hero_threshold))}` : ''}`
        : 'necitită',
    },
    {
      key: 'allowed',
      label: 'Modele permise',
      value: Array.isArray(f.allowed_models)
        ? `${countWords(f.allowed_models.length, 'model', 'modele')}: ${f.allowed_models.join(', ')}`
        : 'toate modelele conexiunii Runway',
    },
    { key: 'narration', label: 'Narațiunea', value: String(f.narration?.line_ro || 'necitită') },
    { key: 'hash', label: 'Amprenta foii', value: String(f.sheet_hash || sheet?.sheet_hash || '').slice(0, 12) },
  ];
}

/** RunPod's recorded estimates, including rejected attempts. @param {any} reading */
function runpodCostRows(reading) {
  if (!reading || !Number(reading.jobs)) return [];
  const accepted = reading.acceptance_by_model || {};
  const rates = Object.entries(accepted).map(([model, r]) => `${model}: ${r.accepted}/${r.reviewed}`);
  const unknown = Number(reading.jobs_with_unknown_cost) || 0;
  return [
    { key: 'runpod_cost', label: reading.provider === 'RUNPOD_MOCK' ? 'RunPod · simulare' : 'RunPod · cost estimat', value: `${usdText(micros(reading.estimated_gpu_cost_usd))}${unknown ? ` + ${unknown} joburi cu cost necunoscut` : ''} · include încercările respinse` },
    { key: 'runpod_scene', label: 'Cost per scenă acceptată', value: usdText(micros(reading.cost_per_accepted_scene_usd)) },
    { key: 'runpod_short', label: 'Cost RunPod per film terminat', value: usdText(micros(reading.cost_per_finished_short_usd)) },
    { key: 'runpod_minutes', label: 'Minute GPU per film terminat', value: reading.gpu_minutes_per_short === null || reading.gpu_minutes_per_short === undefined ? 'necunoscute' : NUMBER.format(Number(reading.gpu_minutes_per_short)) },
    { key: 'runpod_regenerations', label: 'Regenerări RunPod', value: String(reading.regenerations ?? 0) },
    { key: 'runpod_acceptance', label: 'Acceptate / verificate per model', value: rates.join('; ') || 'încă neverificate' },
  ];
}

/* ------------------------------------------------------------------------------- the markup */

/**
 * @typedef {{escape: (value: unknown) => string, confirm?: string|null, notice?: string,
 *   noticeError?: boolean, policy?: any, assembled?: any, ruleOpen?: boolean,
 *   pressed?: TakePress|null, choice?: TakeChoice|null}} SheetOptions
 */
/**
 * TAKE_CHOICE_SEEN: the take button he pressed, while the studio answers.
 * @typedef {{take: string, decision: string}} TakePress
 */
/**
 * TAKE_CHOICE_SEEN: what the studio answered to his look at a take, shown in the scene he pressed
 * (`message` is the server's `outcome.message_ro`, or the refusal's sentence when `failed`).
 * (`network`: no answer arrived, so the choice may have been made: never said as refused).
 * @typedef {{scene: number, take: string, decision: string, failed: boolean, network?: boolean, message: string}} TakeChoice
 */

/**
 * @param {(value: unknown) => string} e @param {any} take @param {string} what
 * @param {TakePress|null} [pressed] the take button pressed, while the studio answers
 * @param {boolean} [closed] the film is closed («Închide filmul»): its takes are no longer chosen
 *   (the backend answers 409 FILM_CLOSED and queues no continuation), so no button is offered
 */
function takeButtons(e, take, what, pressed = null, closed = false) {
  if (!take || take.status !== 'PAID' || closed) return '';
  const approve = what === 'shot' && take.kind === 'test_shot' ? 'Aprobă cadrul de probă după ce l-ai văzut' : what === 'shot' ? 'Aprobă cadrul' : 'Alege imaginea aceasta';
  const reject = what === 'shot' ? 'Respinge cadrul' : 'Respinge';
  // TAKE_CHOICE_SEEN: the pressed button says it is working, and both of its take's buttons hold
  const held = Boolean(pressed && pressed.take === take.take_id);
  /** @param {string} decision @param {string} words @param {string} working */
  const one = (decision, words, working) => {
    const busy = held && pressed?.decision === decision;
    return `<button type="button" class="quiet sheet-take-btn" data-sheet-action="take" data-take="${e(take.take_id)}" data-decision="${decision}"`
      + `${held ? ' disabled' : ''}${busy ? ' aria-busy="true"' : ''}>${e(busy ? working : words)}</button>`;
  };
  return `<div class="sheet-take-actions">`
    + one('APPROVED', approve, what === 'shot' ? 'Se aprobă…' : 'Se alege…')
    + one('REJECTED', reject, 'Se respinge…')
    + '</div>';
}

/**
 * Whether a take is a vendor's refusal that cost nothing (`refusal.credits` 0): such takes are
 * grouped, closed, under «Refuzate de furnizor (0 credite)» so the bought candidates stay in view.
 * @param {any} take
 */
function freeRefusal(take) {
  return take?.status === 'REFUSED' && take?.refusal && typeof take.refusal === 'object' && Number(take.refusal.credits) === 0;
}

/** The vendor's own text, once, behind «Textul furnizorului» ('' without one). @param {(value: unknown) => string} e @param {any} take */
function vendorTextHtml(e, take) {
  const text = take?.refusal?.vendor_text;
  return text ? `<details class="sheet-vendor-text"><summary>Textul furnizorului</summary><p lang="en">${e(text)}</p></details>` : '';
}

/** @param {(value: unknown) => string} e @param {any} take @param {string} [vendor] */
function takeWords(e, take, vendor = 'furnizor') {
  const status = takeStatusWords(take?.status, vendor);
  let why = take?.reason_ro || take?.failure_code;
  // a shot the clip QC rejected says why on its own line (clipQcWords), not twice
  if (take?.clip_qc && String(take?.reason_ro || '').startsWith('Controlul clipului')) why = '';
  // a vendor's refusal in Romanian, with what it cost; its own text goes behind «Textul furnizorului»
  const refusal = take?.status === 'REFUSED' && take?.refusal && typeof take.refusal === 'object' ? take.refusal : null;
  // a cost nobody measured (`credits_known` false) is already said in explain_ro as «până la»;
  // repeating its number here would state it as what the refusal cost
  if (refusal) {
    why = refusal.credits_known === false
      ? `${refusal.explain_ro || why || ''}`
      : `${refusal.explain_ro || why || ''} · ${creditWords(Number(refusal.credits) || 0)}`;
  }
  return `<span class="sheet-take-status" data-status="${e(take?.status)}">${e(status)}</span>${why ? `<span class="sheet-take-why">: ${e(why)}</span>` : ''}`;
}

/**
 * The refusals that cost nothing, in one closed group: each kind of refusal once, counted.
 * @param {(value: unknown) => string} e @param {any[]} takes
 */
function freeRefusalsHtml(e, takes) {
  if (!takes.length) return '';
  /** @type {Map<string, {take: any, count: number}>} */
  const kinds = new Map();
  for (const take of takes) {
    const key = `${take.refusal.explain_ro || ''}\n${take.refusal.vendor_text || ''}`;
    const seen = kinds.get(key);
    if (seen) seen.count += 1;
    else kinds.set(key, { take, count: 1 });
  }
  const rows = [...kinds.values()].map(({ take, count }) => '<li class="sheet-candidate">'
    + `<p>${e(take.refusal.explain_ro || take.reason_ro || '')}${count > 1 ? ` (de ${e(countWords(count, 'dată', 'ori'))})` : ''}</p>`
    + `${vendorTextHtml(e, take)}</li>`).join('');
  return `<details class="sheet-refused"><summary>Refuzate de furnizor (0 credite): ${e(countWords(takes.length, 'cerere', 'cereri'))}</summary>`
    + `<ul class="sheet-candidates">${rows}</ul></details>`;
}

/**
 * TAKE_CHOICE_SEEN: what his look at a take in this scene did, said in the scene's card (the
 * status line at the top says it too). '' for any other scene, or when he pressed nothing.
 * @param {(value: unknown) => string} e @param {any} scene @param {TakeChoice|null|undefined} choice
 */
function choiceNoteHtml(e, scene, choice) {
  if (!choice || Number(choice.scene) !== Number(scene?.scene_index)) return '';
  const shot = (Array.isArray(scene.shots) ? scene.shots : []).some((/** @type {any} */ s) => s?.take_id === choice.take);
  const approved = choice.decision === 'APPROVED';
  let head = approved ? 'Aleasă acum.' : 'Respinsă acum.';
  if (shot) head = approved ? 'Aprobat acum.' : 'Respins acum.';
  // no answer is not a refusal: the server may have recorded his choice before the page stopped
  // waiting, and the sheet read again right after says what is chosen now
  if (choice.failed && choice.network) {
    const what = shot ? 'cadrul aprobat acum' : 'imaginea aleasă acum';
    return `<p class="sheet-choice-note sheet-waiting" role="status"><strong>Răspunsul nu a sosit.</strong> ${e(`Decizia ta poate fi înregistrată pe server: foaia de mai jos, citită din nou, arată ${what}. Uită-te la ea înainte să apeși din nou.`)}</p>`;
  }
  if (choice.failed) head = approved ? 'Alegerea nu s-a făcut.' : 'Respingerea nu s-a făcut.';
  const message = choice.message ? ` ${e(choice.message)}` : '';
  return choice.failed
    ? `<p class="sheet-choice-note sheet-blocked" role="alert"><strong>${e(head)}</strong>${message}</p>`
    : `<p class="sheet-choice-note" role="status"><strong>${e(head)}</strong>${message}</p>`;
}

/**
 * The question a «Refă» press opens: what it redoes and replaces, its price and cap, the plan it is
 * bound to, the day's budget consent when needed, and his note. '' when it cannot be pressed.
 * @param {any} sheet @param {string|null|undefined} key redoKey(kind, scene) @param {SheetOptions} o
 */
export function redoConfirmHtml(sheet, key, o) {
  const e = o.escape;
  const b = redoFor(sheet, key);
  if (!b || b.disabled || redoWaitsForLease(sheet, b) || closedReason(sheet)) return '';
  const paid = PAID_REDOS.includes(b.kind);
  const lines = [];
  if (b.replaces.length) {
    lines.push(b.kind === 'still'
      ? `Înlocuiește ${countWords(b.replaces.length, 'imagine aprobată', 'imagini aprobate')} după ce o aprobi pe cea nouă.`
      : `Înlocuiește ${countWords(b.replaces.length, 'cadru filmat', 'cadre filmate')} după ce îl aprobi pe cel nou.`);
  }
  if (b.invalidates.length) lines.push(`Retrage și ${countWords(b.invalidates.length, 'cadru filmat', 'cadre filmate')} din imaginea veche; mișcarea se reface apoi separat.`);
  const over = paid && overDailyBudget(sheet, b.cap_usd);
  return `<div class="sheet-confirm sheet-redo-confirm" role="group" aria-label="${e(b.label)}">`
    + `<p class="sheet-confirm-q">${e(`Refaci ${redoWhat(b.kind, b.scene)}?`)}</p>`
    + (b.reason_ro ? `<p>${e(b.reason_ro)}</p>` : '')
    + `<p class="sheet-confirm-price">${e(paid ? `${b.price_ro} · ${b.cap_ro}.` : '0 credite: nu se cumpără nimic, filmul se reface din ce are.')}</p>`
    + lines.map((line) => `<p>${e(line)}</p>`).join('')
    + (paid
      ? `<p class="sheet-confirm-bind">Aprobarea ta se leagă de acest plan de refacere (${e(String(b.plan_hash || '').slice(0, 12))}): dacă planul se schimbă, ea nu mai cumpără nimic.</p>`
      : '')
    + (over
      ? `<label class="sheet-over"><input type="checkbox" data-sheet-over-budget> ${e(`Bugetul zilei: plafonul refacerii (${usdText(micros(b.cap_usd))}) depășește ce a rămas azi (${usdText(micros(sheet.footer.daily_budget.remaining_usd))}).`)} Bifează doar dacă vrei să depășești bugetul pentru această refacere.</label>`
      : '')
    + '<label class="sheet-note">Nota ta (opțional)<textarea data-sheet-note maxlength="500" rows="2"></textarea></label>'
    + `<div class="sheet-confirm-actions"><button type="button" class="sheet-yes" data-sheet-action="confirm-redo" data-kind="${e(b.kind)}" data-scene="${e(b.scene ?? '')}">${paid ? 'Da, aprob și refac' : 'Da, refă (0 credite)'}</button>`
    + '<button type="button" class="quiet" data-sheet-action="cancel-step">Nu acum</button></div>'
    + '</div>';
}

/**
 * One block of «Refă» buttons with their prices, and the question of the one pressed.
 * @param {any} sheet @param {RedoButton[]} buttons @param {string} title @param {SheetOptions} o
 */
function redoBlockHtml(sheet, buttons, title, o) {
  const e = o.escape;
  if (!buttons.length) return '';
  // «Închide filmul»: a closed film is redone no more (the backend answers 409 FILM_CLOSED), so
  // every «Refă» is disabled and the reason is said once for the block.
  const closed = closedReason(sheet);
  const rows = buttons.map((b) => {
    if (closed) {
      return '<div class="sheet-redo-box">'
        + `<button type="button" class="quiet sheet-redo-btn" data-sheet-action="redo" data-kind="${e(b.kind)}" data-scene="${e(b.scene ?? '')}" title="${e(closed)}" disabled>${e(b.label)}</button>`
        + `<span class="sheet-redo-price">${e(b.cap_ro ? `${b.price_ro} · ${b.cap_ro}` : b.price_ro)}</span>`
        + '</div>';
    }
    const balanceReason = redoBalanceReason(sheet, b);
    return '<div class="sheet-redo-box">'
    + `<button type="button" class="quiet sheet-redo-btn" data-sheet-action="redo" data-kind="${e(b.kind)}" data-scene="${e(b.scene ?? '')}" title="${e(b.reason_ro)}"${b.disabled || redoWaitsForLease(sheet, b) || balanceReason ? ' disabled' : ''}>${e(b.label)}</button>`
    + `<span class="sheet-redo-price">${e(b.cap_ro ? `${b.price_ro} · ${b.cap_ro}` : b.price_ro)}</span>`
    + (b.disabled && b.reason_ro ? `<p class="sheet-step-why">${e(b.reason_ro)}</p>` : '')
    + (balanceReason && !b.disabled ? `<p class="sheet-step-why">${e(balanceReason)}</p>` : '')
    + (!b.disabled && redoWaitsForLease(sheet, b) ? `<p class="sheet-step-why">${e(BUSY_SEE_BAR)}</p>` : '')
    // the sound's plan is one short sentence (what it remasters, or that there is no film yet)
    + (!b.disabled && b.kind === 'audio' && b.reason_ro ? `<p class="sheet-redo-why">${e(b.reason_ro)}</p>` : '')
    + '</div>'; }).join('');
  const open = !closed && buttons.map((b) => redoKey(b.kind, b.scene)).includes(String(o.confirm || '')) ? redoConfirmHtml(sheet, o.confirm, o) : '';
  return `<div class="sheet-redos"><p class="sheet-sub">${e(title)}</p>${rows}${closed ? `<p class="sheet-step-why">${e(closed)}</p>` : ''}${open}</div>`;
}

/**
 * Whether the film buys on RunPod's GPU (billed in USD by the second, no credit balance to read):
 * the backend's run_step skips the balance rule for it (`local_step`), so the page never blocks
 * it on, nor speaks of, a Runway balance. @param {any} sheet
 */
function gpuBilled(sheet) {
  const balance = sheet?.footer?.balance || {};
  return balance.applicable === false && balance.billing_mode === 'gpu';
}

/** A redo needs its next purchase and the same margin, never its whole cap. @param {any} sheet @param {RedoButton} b */
function redoBalanceReason(sheet, b) {
  if (b.free || !PAID_REDOS.includes(b.kind) || !b.round_credits || gpuBilled(sheet)) return '';
  const credits = sheet?.footer?.balance?.credits;
  if (credits === null || credits === undefined || !Number.isFinite(Number(credits))) return 'Soldul Runway este necunoscut; reîncarcă foaia înainte de refacere.';
  const margin = Number(sheet?.footer?.balance_rule?.motion?.margin) || BALANCE_MARGIN;
  const needed = Math.ceil(Math.round(b.round_credits * margin * 1e6) / 1e6);
  return Number(credits) < needed ? `Pentru pornire: ${creditWords(needed)}. Lipsesc ${creditWords(needed - Number(credits))}.` : '';
}

/** The SAFETY suggestion the motion step left on a scene, and the press that chooses it. @param {(value: unknown) => string} e @param {any} scene */
function safetyHtml(e, scene) {
  const s = scene?.motion?.safety_suggested;
  if (!s || typeof s !== 'object') return '';
  const model = s.model_id ? String(s.model_id) : '';
  return '<div class="sheet-safety" role="note">'
    + '<p class="sheet-safety-head">Refuz de siguranță la furnizor</p>'
    + (s.refused ? `<p>${e(s.refused)}</p>` : '')
    + (model
      ? `<p>Modelul sugerat: ${e(model)} · ${e(creditWords(s.credits))}${s.reason_ro ? ` — ${e(s.reason_ro)}` : ''}. Nu se cumpără nimic până nu îl alegi și aprobi mișcarea.</p>`
        + `<button type="button" class="quiet sheet-model" data-sheet-action="model" data-scene="${e(scene.scene_index)}" data-model="${e(model)}">Alege ${e(model)} · ${e(creditWords(s.credits))}</button>`
      : `<p>${e(s.reason_ro || 'Niciun model sugerat: alege tu modelul scenei sau o imagine fixă animată local.')}</p>`)
    + '</div>';
}

/** @param {any} sheet @param {any} scene @param {SheetOptions} o */
function liveSceneHtml(sheet, scene, o) {
  const e = o.escape;
  const m = scene.motion || {};
  const index = scene.scene_index;
  // TAKE_CHOICE_SEEN: the chosen picture is marked as such, and the one he chose just now stands out
  // (two near-identical candidates swap places after his choice: the card must still show it).
  const choice = o.choice || null;
  const chosenNow = Boolean(choice && !choice.failed && choice.decision === 'APPROVED' && Number(choice.scene) === Number(index)
    && scene.still && scene.still.take_id === choice.take);
  const still = scene.still
    ? `<figure class="sheet-still-box${chosenNow ? ' sheet-chosen-now' : ''}" data-sheet-choice><img class="sheet-still" data-sheet-src="${e(scene.still.file_url)}" alt="Imaginea aleasă a scenei ${e(index)}">`
      + `<figcaption><span class="sheet-chosen-mark">Imaginea aleasă</span> Aprobată de ${e(scene.still.approved_by || '—')} · ${e(scene.still.model_id || '')}</figcaption></figure>`
    : '<p class="sheet-still-missing">Nicio imagine aprobată încă: scena intră în pasul imaginilor.</p>';
  const pressed = o.pressed || null;
  const closed = Boolean(closedReason(sheet));
  const vendor = gpuBilled(sheet) ? 'RunPod' : 'furnizor';
  const all = Array.isArray(scene.candidates) ? scene.candidates : [];
  const candidates = all.filter((/** @type {any} */ c) => !freeRefusal(c)).map((/** @type {any} */ c) => `<li class="sheet-candidate">`
    + (c.file_url ? `<img class="sheet-thumb" data-sheet-src="${e(c.file_url)}" alt="Candidat pentru scena ${e(index)}">` : '')
    + `<p>${takeWords(e, c, vendor)}</p>${vendorTextHtml(e, c)}${takeButtons(e, c, 'still', pressed, closed)}</li>`).join('');
  const refused = freeRefusalsHtml(e, all.filter(freeRefusal));
  const allShots = Array.isArray(scene.shots) ? scene.shots : [];
  /** @param {any} s */
  const shotHtml = (s) => `<li class="sheet-shot">`
    + `<p>${s.kind === 'test_shot' ? 'Cadrul de probă' : 'Clip'} · ${e(s.model_id || '—')} · ${e(s.seconds ?? '?')} s · ${takeWords(e, s, vendor)}</p>`
    + vendorTextHtml(e, s)
    + (s.file_url ? `<p class="sheet-clip-qc" data-verdict="${e(s.clip_qc?.verdict || 'NONE')}">${e(clipQcWords(s.clip_qc))}</p>` : '')
    + (s.file_url ? `<button type="button" class="quiet sheet-play" data-sheet-action="play" data-sheet-src="${e(s.file_url)}">Redă clipul</button>` : '')
    + `${takeButtons(e, s, 'shot', pressed, closed)}</li>`;
  const current = allShots.filter((/** @type {any} */ s) => s.for_current_prompt !== false && ['PAID', 'APPROVED', 'SUBMITTED'].includes(s.status));
  const history = allShots.filter((/** @type {any} */ s) => !current.includes(s));
  const shots = current.map(shotHtml).join('');
  const media = sceneMediaState(scene);
  const why = m.reason_ro ? `<p class="sheet-why">${e(m.reason_ro)}${m.decided_by === 'owner' ? ' <strong>(alegerea ta)</strong>' : ''}${m.price_source ? ` · ${e(m.price_source)}` : ''}</p>` : '';
  const choices = [];
  if (m.cheaper && m.cheaper.model_id) {
    choices.push(`<button type="button" class="quiet sheet-model" data-sheet-action="model" data-scene="${e(index)}" data-model="${e(m.cheaper.model_id)}">Mai ieftin: ${e(m.cheaper.model_id)} · ${e(creditWords(m.cheaper.credits))}${m.cheaper.why_ro ? ` (${e(m.cheaper.why_ro)})` : ''}</button>`);
  }
  if (m.better && m.better.model_id) {
    choices.push(`<button type="button" class="quiet sheet-model" data-sheet-action="model" data-scene="${e(index)}" data-model="${e(m.better.model_id)}">Mai bun: ${e(m.better.model_id)} · ${e(creditWords(m.better.credits))}</button>`);
  }
  if (m.status !== 'LOCAL' && m.status !== 'BOUGHT') {
    choices.push(`<button type="button" class="quiet sheet-model" data-sheet-action="model" data-scene="${e(index)}" data-model="LOCAL_MOVE">Imagine fixă animată local · 0 credite</button>`);
  }
  if (scene.override !== null && scene.override !== undefined) {
    choices.push(`<button type="button" class="quiet sheet-model" data-sheet-action="model" data-scene="${e(index)}" data-model="">Revino la alegerea studioului</button>`);
  }
  const findings = (Array.isArray(scene.lint) ? scene.lint : []).map((/** @type {any} */ f) => `<li class="sheet-finding" data-severity="${e(f.severity)}">${e(f.message_ro)}</li>`).join('');
  const badges = (Array.isArray(scene.badges) ? scene.badges : []).map((/** @type {any} */ b) => `<li class="sheet-badge" title="${e(`sursa: ${b.source || '—'}`)}">${e(b.label_ro)}</li>`).join('');
  const lint = lintLine(scene);
  const guidance = media.generated ? 'Leagă aprobarea de clipul pe care l-ai văzut.'
    : media.tone === 'alert' ? 'Cererea a fost refuzată. Nu există un fișier video; folosește „Refă mișcarea” pentru o nouă încercare.'
      : media.tone === 'info' ? 'Cererea a fost trimisă; rezultatul nu este disponibil încă.'
        : media.tone === 'warn' ? 'Clipul respins nu intră în film. Poți reface doar mișcarea acestei scene.'
          : media.label === 'Animație locală aleasă' ? 'Filmul va folosi mișcarea locală a imaginii, la asamblare.'
            : scene.still ? 'Imaginea este aleasă. Mișcarea nu a fost generată încă.' : 'Generează și alege întâi imaginea acestei scene.';
  return '<div class="sheet-scene-layout">'
    + `<div class="sheet-scene-preview">${still}</div>`
    + '<div class="sheet-scene-work">'
    + `<p class="sheet-media-state" data-tone="${e(media.tone)}">${e(media.label)}</p><p class="sheet-media-guidance">${e(guidance)}</p>`
    + choiceNoteHtml(e, scene, choice)
    + (scene.narration ? `<blockquote class="sheet-narration" lang="en"><span>Narațiune</span>«${e(scene.narration)}»</blockquote>` : '')
    + safetyHtml(e, scene)
    + (shots ? `<ul class="sheet-shots">${shots}</ul>` : '')
    + redoBlockHtml(sheet, redoButtons(scene), 'Refă doar această scenă', o)
    + '</div><div class="sheet-scene-options">'
    + '<details class="sheet-production-details"><summary>Model, prompturi și verificări</summary><div class="sheet-details-content">'
    + `${why}${choices.length ? `<div class="sheet-models">${choices.join('')}</div>` : ''}`
    + `<p class="sheet-still-price">Imaginea: ${e(creditWords(scene.still_credits))} (${e(scene.still_price_source || 'fără preț')}) · sămânța ${e(m.seed ?? '—')}</p>`
    + (badges ? `<ul class="sheet-badges">${badges}</ul>` : '')
    + `<p class="sheet-lint">Verificarea prompturilor: <strong class="${lint === 'curat' ? 'sheet-ok' : 'sheet-warn'}">${e(lint)}</strong></p>`
    + (findings ? `<ul class="sheet-findings">${findings}</ul>` : '')
    + `<details class="sheet-prompt"><summary>Vezi promptul imaginii</summary><p lang="en">${e(scene.still_prompt)}</p></details>`
    + `<details class="sheet-prompt"><summary>Vezi promptul de mișcare</summary><p lang="en">${e(scene.motion_prompt)}</p>`
    + (scene.negative_prompt ? `<p class="sheet-negative">Prompt negativ: <span lang="en">${e(scene.negative_prompt)}</span></p>` : '')
    + '</details></div></details>'
    + (candidates || refused ? `<details class="sheet-alternatives"><summary>Alte imagini (${e(all.length)})</summary><div class="sheet-details-content">${candidates ? `<ul class="sheet-candidates">${candidates}</ul>` : ''}${refused}</div></details>` : '')
    + (history.length ? `<details class="sheet-shot-history"><summary>Încercări anterioare (${e(history.length)})</summary><ul class="sheet-shots">${history.map(shotHtml).join('')}</ul></details>` : '')
    + '</div></div>';
}

/** @param {any} sheet @param {any} scene @param {SheetOptions} o */
function cardSceneHtml(sheet, scene, o) {
  const e = o.escape;
  const card = scene.card || {};
  const spec = card.card_json || {};
  const bars = (Array.isArray(spec.bars) ? spec.bars : []).map((/** @type {any} */ b) => `<li>${e(b.label)}: ${e(cardValue(b.value))} ${e(b.unit)}</li>`).join('');
  return `<div class="sheet-scene-preview">${card.preview_url ? `<figure class="sheet-still-box"><img class="sheet-still" data-sheet-src="${e(card.preview_url)}" alt="Previzualizarea scenei ${e(scene.scene_index)}, compusă local"></figure>` : '<div class="sheet-card-placeholder">Scenă compusă local<br>0 credite Runway</div>'}</div>`
    + '<div class="sheet-scene-work">'
    + (spec.title ? `<p class="sheet-card-title">${e(spec.title)}</p>` : '')
    + (bars ? `<ul class="sheet-card-bars">${bars}</ul>` : '')
    + (spec.cta ? `<p class="sheet-card-cta">${e(spec.cta)}</p>` : '')
    + (card.problem_ro ? `<p class="sheet-problem">${e(card.problem_ro)}</p>` : '')
    + `<p class="sheet-why">${e(COMPOSED_WHY[/** @type {keyof typeof COMPOSED_WHY} */ (scene.kind)] || COMPOSED_WHY.DATA_CARD)}</p>`
    + redoBlockHtml(sheet, redoButtons(scene), 'Refă doar această scenă', o) + '</div>';
}

/**
 * The question a step's button opens: what is bought, its price and cap, the sheet it is bound to,
 * the daily budget's consent when it is needed, and his note. '' when the step cannot be pressed.
 * The assembly's question says what it voices and what it costs.
 * @param {any} sheet @param {string} step @param {SheetOptions} o
 */
export function stepConfirmHtml(sheet, step, o) {
  const e = o.escape;
  const hash = String(sheet?.sheet_hash || '').slice(0, 12);
  const bind = `<p class="sheet-confirm-bind">Aprobarea ta se leagă de această foaie (${e(hash)}): dacă foaia se schimbă, ea nu mai cumpără nimic.</p>`;
  const note = '<label class="sheet-note">Nota ta (opțional)<textarea data-sheet-note maxlength="500" rows="2"></textarea></label>';
  const cancel = '<button type="button" class="quiet" data-sheet-action="cancel-step">Nu acum</button>';
  if (step === ASSEMBLE_STEP) {
    const a = assembleButton(sheet);
    if (a.disabled) return '';
    return `<div class="sheet-confirm" role="group" aria-label="${e(a.label)}">`
      + '<p class="sheet-confirm-q">Asamblezi filmul din cadrele acceptate?</p>'
      + `<p class="sheet-confirm-price">${e(a.price_ro)}.</p>`
      + (a.line_ro ? `<p>${e(a.line_ro)}</p>` : '')
      + '<p>Urmează masterul, controlul calității și scrisoarea lui către tine; nimic de la Runway nu se cumpără la acest pas.</p>'
      + bind + note
      + `<div class="sheet-confirm-actions"><button type="button" class="sheet-yes" data-sheet-action="confirm-step" data-step="${e(ASSEMBLE_STEP)}">Da, asamblează</button>${cancel}</div>`
      + '</div>';
  }
  const b = stepButtons(sheet).find((x) => x.step === step);
  if (!b || b.disabled) return '';
  const scenes = b.to_buy.length === 1 ? `Scena ${b.to_buy[0]}` : `Scenele ${b.to_buy.join(', ')}`;
  return `<div class="sheet-confirm" role="group" aria-label="${e(b.label)}">`
    + `<p class="sheet-confirm-q">${e(STEP_QUESTIONS[/** @type {keyof typeof STEP_QUESTIONS} */ (step)])}</p>`
    + `<p>${e(scenes)} · ${e(b.price_ro)} · ${e(b.cap_ro)}.</p>`
    + bind
    + (b.over_budget
      ? `<label class="sheet-over"><input type="checkbox" data-sheet-over-budget> ${e(b.over_budget_ro)} Bifează doar dacă vrei să depășești bugetul pentru acest pas.</label>`
      : '')
    + note
    + `<div class="sheet-confirm-actions"><button type="button" class="sheet-yes" data-sheet-action="confirm-step" data-step="${e(step)}">Da, aprob și cumpăr</button>${cancel}</div>`
    + '</div>';
}

/**
 * What the assembly answered: the QC verdict, its reasons and the Owner's QC letter, whole.
 * '' when nothing came back yet.
 * @param {any} result POST .../steps/assemble 200
 * @param {{escape: (value: unknown) => string}} o
 */
export function assembleResultHtml(result, o) {
  if (!result || typeof result !== 'object') return '';
  const e = o.escape;
  const qc = result.qc && typeof result.qc === 'object' ? result.qc : {};
  const status = String(qc.status || '');
  const verdict = status === 'PASSED' ? 'trecut' : status === 'FAILED' ? 'picat' : status ? status.toLowerCase() : 'nerulat';
  const reasons = (Array.isArray(qc.failure_reasons_json) ? qc.failure_reasons_json : []).map((/** @type {unknown} */ r) => `<li>${e(r)}</li>`).join('');
  const narration = result.narration && typeof result.narration === 'object' ? result.narration : null;
  const voice = narration ? `Narațiunea: ${usdText(narration.usd_micros)}${narration.asked ? ', cu aprobarea ta' : ''}` : '';
  return `<div class="sheet-qc" data-verdict="${e(status || 'NONE')}" role="status">`
    + `<p class="sheet-qc-head">Filmul a fost asamblat · Controlul calității: ${e(verdict)}</p>`
    + `<p class="sheet-qc-meta">${e([voice, result.job_id ? `randarea ${String(result.job_id).slice(0, 8)}` : ''].filter(Boolean).join(' · '))}</p>`
    + (reasons ? `<ul class="sheet-qc-reasons">${reasons}</ul>` : '')
    + (result.qc_letter_ro
      ? `<details class="sheet-letter-box"${status === 'FAILED' ? ' open' : ''}><summary>Scrisoarea controlului calității</summary><div class="sheet-letter">${e(result.qc_letter_ro)}</div></details>`
      : '')
    + '</div>';
}

/**
 * PAGE-14: what the sheet asks of him, before the 2,000 px of scenes: his rule, the next step
 * with its price and cap (the first paid step that still has something to buy, else the
 * assembly), and whether it can be pressed now.
 * @param {any} sheet
 * @param {any} policy the page's `/snapshot` policy, or null (the sheet's own owner_rule then)
 * @returns {{rule_ro: string, next: {step: string, label: string, price_ro: string, cap_ro: string, disabled: boolean, reason_ro: string}|null}}
 */
export function sheetSummary(sheet, policy) {
  const rule = policy
    ? { paid_media_approval: policy.paid_media_approval, over_usd: policy.paid_media_approval_over_usd }
    : sheet?.owner_rule;
  const step = stepButtons(sheet).find((b) => b.to_buy.length > 0);
  if (step) {
    return { rule_ro: paidMediaRuleWords(rule), next: { step: step.step, label: step.label, price_ro: step.price_ro, cap_ro: step.cap_ro, disabled: step.disabled, reason_ro: step.reason_ro } };
  }
  const a = assembleButton(sheet);
  return { rule_ro: paidMediaRuleWords(rule), next: { step: ASSEMBLE_STEP, label: a.label, price_ro: a.price_ro, cap_ro: '', disabled: a.disabled, reason_ro: a.reason_ro } };
}

/** The overview at the top, scrolling with the sheet. @param {any} sheet @param {SheetOptions} o */
function sheetSummaryHtml(sheet, o) {
  const e = o.escape;
  const summary = sheetSummary(sheet, o.policy || null);
  const next = summary.next;
  const busy = inProgressReason(sheet);
  const progress = sheetProgress(sheet);
  const recovery = testShotRecovery(sheet);
  const heroScene = (sheet?.scenes || []).find((/** @type {any} */ s) => Number(s.scene_index) === Number(sheet?.footer?.hero_scene));
  const reviewHero = heroScene && sceneMediaState(heroScene).generated && !heroState(sheet).approved && !HERO_LETS_MOTION.includes(sheet?.steps?.motion?.hero?.status);
  const balance = sheet?.footer?.balance?.credits;
  const balanceWords = balance !== null && balance !== undefined && Number.isFinite(Number(balance)) ? creditWords(Number(balance)) : 'Necunoscut';
  return '<div class="sheet-summary-bar" role="region" aria-label="Pe scurt">'
    + `<h2 class="sheet-title">${e(String(sheet?.title || '').replace(/^Storyboard:\s*/i, ''))}</h2>`
    + '<dl class="sheet-progress">'
    + `<div><dt>Imagini aprobate</dt><dd>${e(progress.images)} / ${e(progress.filmed)}</dd></div>`
    + `<div><dt>Clipuri disponibile</dt><dd>${e(progress.clips)} / ${e(progress.filmed - progress.local)}${progress.local ? ` <small>+ ${e(progress.local)} local</small>` : ''}</dd></div>`
    + `<div><dt>Scene compuse local</dt><dd>${e(progress.cards)}</dd></div>`
    + (gpuBilled(sheet)
      ? '<div><dt>RunPod GPU</dt><dd>Cost estimat în USD, plătit la secundă</dd></div></dl>'
      : `<div><dt>Sold Runway</dt><dd>${e(balanceWords)}</dd></div></dl>`)
    + (recovery && !busy ? `<p class="sheet-summary-next">Următorul pas: <strong>Reia clipul de probă</strong> (scena ${e(recovery.scene)}) · ${e(recovery.price_ro)} · ${e(recovery.cap_ro)}${redoBalanceReason(sheet, recovery) ? ` <span class="sheet-summary-why">${e(redoBalanceReason(sheet, recovery))}</span>` : ''}</p>` : '')
    + (reviewHero && !busy ? `<p class="sheet-summary-next">Următorul pas: <strong>Vezi și aprobă clipul de probă</strong> (scena ${e(heroScene.scene_index)}).</p>` : '')
    + (next && ((!recovery && !reviewHero) || busy)
      ? `<p class="sheet-summary-next">Următorul pas: <strong>${e(next.label)}</strong> · ${e(next.price_ro)}${next.cap_ro ? ` · ${e(next.cap_ro)}` : ''}${next.disabled ? ` <span class="sheet-summary-why">— ${e(busy || next.reason_ro)}</span>` : ''}</p>`
      : '')
    + '<button type="button" class="quiet sheet-summary-go" data-sheet-action="to-steps">Mergi la pași</button>'
    + '</div>';
}

/** The production sequence, before the scenes, with the backend's gates and prices. @param {any} sheet @param {SheetOptions} o */
function workflowHtml(sheet, o) {
  const e = o.escape;
  const progress = sheetProgress(sheet);
  const recovery = testShotRecovery(sheet);
  const hero = heroState(sheet);
  const heroScene = (sheet?.scenes || []).find((/** @type {any} */ s) => Number(s.scene_index) === Number(hero.scene));
  const remainingScenes = (sheet?.scenes || []).filter((/** @type {any} */ s) => !isCard(s) && Number(s.scene_index) !== hero.scene);
  const motionAvailable = remainingScenes.every((/** @type {any} */ s) => s.motion?.status === 'LOCAL' || sceneMediaState(s).generated);
  const motionReview = remainingScenes.find((/** @type {any} */ s) => sceneMediaState(s).take?.status === 'PAID');
  const busy = inProgressReason(sheet);
  /** @param {string[]} reasons */
  const fullReasons = (reasons) => [...new Set(reasons.map((r) => busy && r === busy ? BUSY_SEE_BAR : r))];
  /** @param {string[]} reasons */
  const reasonDetails = (reasons) => reasons.length ? `<details class="sheet-step-details"><summary>Detalii blocaj</summary><ul>${fullReasons(reasons).map((r) => `<li>${e(r)}</li>`).join('')}</ul></details>` : '';
  /** @param {any} b */
  const shortReason = (b) => {
    if (busy) return BUSY_SEE_BAR;
    if (sheet?.lint_blocked) return 'Prompturile au blocaje. Vezi verificările scenelor.';
    if (sheet?.shot_plan_gaps?.length) return `Lipsește planul scenelor ${sheet.shot_plan_gaps.join(', ')}.`;
    const reasons = [];
    if (b.step === 'motion' && b.reasons.some((/** @type {string} */ r) => /cadrul de probă/i.test(r))) reasons.push(`Întâi rezolvă clipul de probă (scena ${hero.scene}).`);
    const balance = sheet?.footer?.balance?.credits;
    const needed = sheet?.footer?.balance_needed_credits?.[b.step];
    if (gpuBilled(sheet)) { /* RunPod: no balance to read; the cap and the daily budget apply */ }
    else if (b.to_buy.length && (balance === null || balance === undefined || !Number.isFinite(Number(balance)))) reasons.push('Soldul Runway este necunoscut. Reîncarcă foaia.');
    else if (b.to_buy.length && needed !== null && needed !== undefined && Number.isFinite(Number(needed)) && Number(balance) < Number(needed)) reasons.push(`Pentru pornire: ${creditWords(Number(needed))}. Lipsesc ${creditWords(Number(needed) - Number(balance))}.`);
    return reasons.join(' ') || (b.disabled ? b.reasons[0] || 'Așteaptă pasul anterior.' : 'Poți porni acest pas.');
  };
  const titles = { stills: 'Imaginile scenelor', test_shot: 'Clipul de probă', motion: 'Toate clipurile rămase' };
  const rows = stepButtons(sheet).map((b, index) => {
    const held = b.step === 'test_shot' ? recovery : null;
    const unnecessary = b.step === 'stills' ? progress.filmed === 0
      : b.step === 'test_shot' ? hero.scene === null
        : remainingScenes.length === 0;
    const done = b.step === 'stills' ? progress.images === progress.filmed
      : b.step === 'test_shot' ? hero.approved || HERO_LETS_MOTION.includes(sheet?.steps?.motion?.hero?.status)
        : !busy && !b.to_buy.length && motionAvailable;
    const review = b.step === 'test_shot' ? !done && heroScene && sceneMediaState(heroScene).generated
      : b.step === 'motion' && done && motionReview;
    const reviewScene = b.step === 'test_shot' ? hero.scene : motionReview?.scene_index;
    const state = held ? sceneMediaState(heroScene).label : unnecessary ? 'Nu este necesar' : review ? 'De verificat' : done ? 'Gata' : b.disabled ? 'În așteptare' : 'Pregătit';
    const tone = held ? sceneMediaState(heroScene).tone : review ? 'warn' : done ? 'ok' : b.disabled ? 'quiet' : 'info';
    const detail = held ? `Scena ${held.scene} nu are un clip acceptat. Reia mișcarea din acțiunile scenei. ${redoBalanceReason(sheet, held)}`
      : unnecessary ? 'Planul filmului nu cere acest pas.'
      : review ? b.step === 'test_shot' ? 'Clipul există. Redă-l și aprobă-l înainte de celelalte scene.' : 'Clipurile există. Verifică rezultatele în scenele de mai jos.'
      : done && b.step === 'stills' ? `${progress.images} din ${progress.filmed} imagini aprobate.`
        : done ? b.step === 'test_shot' ? 'Clipul de probă este acceptat.' : 'Toate scenele rămase au clip sau animație locală.' : shortReason(b);
    const scope = b.step === 'motion' && b.to_buy.length
      ? `<p class="sheet-step-scope">O singură aprobare pentru scenele ${e(b.to_buy.join(', '))}. Se procesează automat, pe rând.</p>` : '';
    const action = held || review
      ? `<button type="button" class="quiet sheet-step" data-sheet-action="to-scene" data-scene="${e(held ? held.scene : reviewScene)}">Deschide scena ${e(held ? held.scene : reviewScene)}</button>`
      : done || unnecessary ? '<span class="sheet-step-done">Nicio acțiune necesară</span>'
      : `<button type="button" class="sheet-step" data-sheet-action="step" data-step="${e(b.step)}"${b.disabled ? ' disabled' : ''}>${e(b.label)}</button>`;
    return `<div class="sheet-step-box" data-step-state="${e(state)}">`
      + `<div class="sheet-step-main"><span class="sheet-step-index" aria-hidden="true">${index + 1}</span><h3>${e(titles[/** @type {keyof typeof titles} */ (b.step)])}</h3><span class="sheet-step-state" data-tone="${e(tone)}">${e(state)}</span></div>`
      + `<div class="sheet-step-copy"><p class="sheet-step-explain">${e(detail)}</p>${scope}${done || unnecessary ? '' : reasonDetails(b.reasons)}</div>`
      + `<div class="sheet-step-action"><span class="sheet-step-price">${e(held ? held.price_ro : done || review || unnecessary ? 'Nimic de cumpărat' : b.price_ro)}</span>`
      + (!done && !review && !unnecessary ? `<span class="sheet-step-cap">${e(held ? held.cap_ro : b.cap_ro)}</span>` : '') + action + '</div>'
      + (b.over_budget && !b.disabled ? `<p class="sheet-step-warn">${e(b.over_budget_ro)}</p>` : '')
      + (o.confirm === b.step ? stepConfirmHtml(sheet, b.step, o) : '') + '</div>';
  }).join('');
  const a = assembleButton(sheet);
  const blocked = sheet?.steps?.assemble?.blocked || [];
  const assemble = '<div class="sheet-step-box sheet-assemble">'
    + `<div class="sheet-step-main"><span class="sheet-step-index" aria-hidden="true">4</span><h3>Asamblarea filmului</h3><span class="sheet-step-state" data-tone="${a.disabled ? 'quiet' : 'info'}">${a.disabled ? 'În așteptare' : 'Pregătit'}</span></div>`
    + `<div class="sheet-step-copy"><p class="sheet-step-explain">${e(busy ? BUSY_SEE_BAR : blocked.length ? `Așteaptă clipurile scenelor ${[...new Set(blocked.map((/** @type {any} */ b) => b.scene_index))].join(', ')}.` : a.disabled ? 'Finalizează pașii de producție înainte de asamblare.' : 'Unește scenele, narațiunea și subtitrările; apoi rulează controlul calității.')}</p>${reasonDetails(a.reasons)}</div>`
    + `<div class="sheet-step-action"><span class="sheet-step-price">${e(a.price_ro)}</span><button type="button" class="sheet-step" data-sheet-action="step" data-step="assemble"${a.disabled ? ' disabled' : ''}>${e(a.label)}</button></div>`
    + (o.confirm === ASSEMBLE_STEP ? stepConfirmHtml(sheet, ASSEMBLE_STEP, o) : '')
    + assembleResultHtml(o.assembled, o) + '</div>';
  return `<section class="sheet-footer" id="sheet-steps" aria-label="Pașii producției"><div class="sheet-section-heading"><h2>Pașii producției</h2><p>Fiecare acțiune plătită arată costul și plafonul înainte de aprobare.</p></div><div class="sheet-steps">${rows}${assemble}</div></section>`;
}

/**
 * The whole drawer's content.
 * @param {any} sheet GET /media/storyboards/{id}/shooting-sheet
 * @param {SheetOptions} o
 */
export function sheetHtml(sheet, o) {
  const e = o.escape;
  const scenes = Array.isArray(sheet?.scenes) ? sheet.scenes : [];
  const hash = String(sheet?.sheet_hash || '').slice(0, 12);
  const gaps = Array.isArray(sheet?.shot_plan_gaps) ? sheet.shot_plan_gaps : [];
  const blocks = (Array.isArray(sheet?.blocks) ? sheet.blocks : []).map((/** @type {any} */ f) => `<li>${e(f.message_ro)}</li>`).join('');
  const rule = o.policy
    ? { paid_media_approval: o.policy.paid_media_approval, over_usd: o.policy.paid_media_approval_over_usd }
    : sheet?.owner_rule;
  const problem = sheet?.footer?.catalogue_problem_ro;
  const head = '<header class="sheet-head">'
    + `<div class="sheet-rule-line"><p class="sheet-rule">${e(paidMediaRuleWords(rule))}</p>`
    + `<details class="sheet-rule-box"${o.ruleOpen ? ' open' : ''}><summary>Schimbă regula</summary>${paidMediaFormHtml(o.policy || null, o)}</details></div>`
    + '<details class="sheet-specs"><summary>Detalii de producție</summary>'
    + `<p class="sheet-meta">Rezoluție ${e(sheet?.resolution || '—')} · sămânța filmului ${e(sheet?.seed ?? '—')} · foaia ${e(hash)}</p>`
    + (sheet?.reference_images_verified === false
      ? '<p class="sheet-flag">Imaginile scenelor 2 și următoarele folosesc imaginea scenei 1 ca referință (lumină, paletă, granulație). Pe acest cont efectul este încă nevalidat, până la primul pas aprobat.</p>'
      : '') + '</details>'
    + (problem ? `<p class="sheet-flag sheet-blocked">Lista ta de modele (config/film_models.json) nu a putut fi citită: ${e(problem)}</p>` : '')
    + (gaps.length ? `<p class="sheet-flag sheet-blocked">Scenele ${e(gaps.join(', '))} nu au planul de cadre scris de model; filmul așteaptă planul de cadre.</p>` : '')
    + (sheet?.lint_summary_ro ? `<p class="sheet-lint-summary${sheet?.lint_blocked ? ' sheet-blocked' : ''}">${e(sheet.lint_summary_ro)}</p>` : '')
    + (blocks ? `<ul class="sheet-findings sheet-blocked">${blocks}</ul>` : '')
    + (o.notice ? `<p class="sheet-notice${o.noticeError ? ' sheet-blocked' : ''}" role="status">${e(o.notice)}</p>` : '')
    + '</header>';
  // data-scene-index: the page keeps the scene he pressed in view after the repaint (TAKE_CHOICE_SEEN)
  const list = scenes.map((/** @type {any} */ scene) => `<li class="sheet-scene" data-kind="${e(scene.kind)}" data-scene-index="${e(scene.scene_index)}">`
    + `<h3 class="sheet-scene-line" tabindex="-1">${e(sceneLine(scene))}</h3>`
    + (isCard(scene) ? `<div class="sheet-scene-layout sheet-card-layout">${cardSceneHtml(sheet, scene, o)}</div>` : liveSceneHtml(sheet, scene, o))
    + '</li>').join('');
  const rows = footerRows(sheet).map((r) => `<div class="sheet-row" data-key="${e(r.key)}"><dt>${e(r.label)}</dt><dd>${e(r.value)}</dd></div>`).join('');
  const sound = audioRedoButton(sheet);
  const repair = sheet?.remediation;
  /** @type {Record<string, string>} */
  const repairWords = {
    QUEUED: 'Trimis Directorului', CLAIMED: 'Remediere în lucru', RUNNING: 'Remediere în lucru',
    REVISED: 'Remedierea continuă pe foaia revizuită',
    RESOLVED: 'Blocajele foii sunt rezolvate', UNRESOLVED: 'Blocajele rămân deschise',
    WAITING_OWNER: 'Așteaptă decizia ta', STALE: 'Foaia s-a schimbat; raportul vechi a fost oprit',
    DEAD_LETTER: 'Remedierea s-a oprit', BLOCKED: 'Remedierea este oprită de politica studioului',
  };
  const remediation = repair ? `<details class="sheet-warning"><summary>${e(repairWords[repair.status] || 'Starea remedierii: ' + repair.status)}</summary><p>${e(repair.reason || '')}</p></details>` : '';
  // «Închide filmul»: a closed film says so under the summary; an open one has the button after
  // its production steps.
  const close = closeFilmHtml(sheet, o);
  const closed = Boolean(sheet?.closure?.closed);
  return `${sheetSummaryHtml(sheet, o)}${closed ? close : ''}${head}${workflowHtml(sheet, o)}${closed ? '' : close}${remediation}`
    + `<section class="sheet-scenes-section" aria-label="Scenele filmului"><div class="sheet-section-heading"><h2>Scenele filmului</h2><p>Imaginea aleasă, starea clipului și acțiunile fiecărei scene.</p></div><ol class="sheet-scenes">${list}</ol></section>`
    + `<details class="sheet-budget"><summary>Costuri, bugete și alternative</summary><div class="sheet-details-content"><dl class="sheet-rows">${rows}</dl>`
    + (sheet?.footer?.summary_ro ? `<p class="sheet-summary">${e(sheet.footer.summary_ro)}</p>` : '')
    + (sound ? `<div class="sheet-redo-audio">${redoBlockHtml(sheet, [sound], 'Sunetul filmului', o)}</div>` : '')
    + '</div></details>';
}

/* ------------------------------------------------------------------------- talking to the studio */

/** @param {string} storyboardId */
export function sheetPath(storyboardId) {
  return `/media/storyboards/${storyboardId}/shooting-sheet`;
}

/** @param {string} storyboardId @param {string} step */
export function stepPath(storyboardId, step) {
  return `/media/storyboards/${storyboardId}/steps/${step}`;
}

/** @param {string} storyboardId @param {number|string} sceneIndex */
export function sceneModelPath(storyboardId, sceneIndex) {
  return `/media/storyboards/${storyboardId}/shooting-sheet/scenes/${sceneIndex}/model`;
}

/** @param {string} takeId */
export function takeDecisionPath(takeId) {
  return `/media/takes/${takeId}/decision`;
}

/** The legacy render route (TEST only; PRODUCTION answers 409). @param {string} storyboardId */
export function renderPath(storyboardId) {
  return `/media/render/${storyboardId}`;
}

/**
 * What a failed POST /media/render means: the sheet, when the studio said «Folosește foaia de
 * filmare» (409 UseShootingSheet), otherwise the error as it came.
 * @param {any} error as main.js's api() throws it ({status, detail})
 */
export function renderAnswer(error) {
  const detail = error && error.detail;
  if (error && error.status === 409 && detail && typeof detail === 'object' && detail.error === 'UseShootingSheet') {
    return { sheet: true, message: String(detail.message || '') };
  }
  return { sheet: false, message: String((error && error.message) || '') };
}

/**
 * The render button: it POSTs /media/render once; when the studio answers 409 «use the sheet» it
 * opens the sheet, and from then on it opens the sheet without posting again.
 * @param {(path: string, options?: any) => Promise<any>} api
 * @param {string} storyboardId
 * @param {{sheetFirst: boolean}} state kept by the caller across presses
 * @param {(storyboardId: string, message: string) => unknown} openSheet
 */
export async function requestRender(api, storyboardId, state, openSheet) {
  if (state.sheetFirst) {
    await openSheet(storyboardId, '');
    return { opened: true, posted: false, message: '' };
  }
  try {
    await api(renderPath(storyboardId), { method: 'POST' });
    return { rendered: true, opened: false };
  } catch (error) {
    const answer = renderAnswer(error);
    if (!answer.sheet) throw error;
    state.sheetFirst = true;
    await openSheet(storyboardId, answer.message);
    return { opened: true, posted: true, message: answer.message };
  }
}

/**
 * PAGE-06: what the drawer says while a press is being bought. A paid step runs on the server
 * for up to 45 minutes (STEP_TIMEOUT_MS); the page says so, and that a second press is not
 * needed, instead of leaving the last notice up.
 * @param {string} what a step (stills, test_shot, motion, assemble) or a redo key (redoKey)
 */
export function buyingNotice(what) {
  const tail = ': poate dura până la 45 de minute. Nu cumpăra din nou; foaia se reîncarcă singură.';
  const redo = parseRedoKey(what);
  if (redo) return `${redo.kind === 'still' || redo.kind === 'motion' ? 'Se reface' : 'Se reface (0 credite)'} ${redoWhat(redo.kind, redo.scene)}${tail}`;
  if (what === ASSEMBLE_STEP) return `Se asamblează filmul${tail}`;
  return `Se cumpără ${STEP_WORDS[/** @type {keyof typeof STEP_WORDS} */ (what)] || what}${tail}`;
}

/**
 * A press whose answer never reached the page (a dropped connection, the page's own timeout)
 * may still be buying on the server: said so, never as a refusal.
 */
export const NETWORK_STEP_WORDS = 'Răspunsul nu a ajuns; cumpărarea poate continua pe server. Reîncarcă foaia peste câteva minute înainte de orice altă apăsare.';

/** @param {any} body */
function asksOwner(body) {
  return Boolean(body && body.status === 'NEEDS_APPROVAL');
}

/**
 * A refusal in the backend's own words, with the scenes it names (the assembly's 409 names each
 * filmed scene that has no accepted take).
 * @param {any} error
 * @returns {{status: 'REFUSED', code: string|null, message: string, scenes: string[]}}
 */
function refused(error) {
  if (error && error.network) return { status: 'REFUSED', code: 'NETWORK', message: NETWORK_STEP_WORDS, scenes: [] };
  const detail = error && error.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const scenes = (Array.isArray(detail.scenes) ? detail.scenes : [])
      .map((/** @type {any} */ s) => String((s && typeof s === 'object' ? s.reason_ro : s) || '').trim())
      .filter(Boolean);
    return { status: 'REFUSED', code: detail.status || detail.error || null, message: String(detail.message || error.message || ''), scenes };
  }
  return { status: 'REFUSED', code: null, message: String((error && error.message) || detail || ''), scenes: [] };
}

/**
 * @typedef {{status: 'DONE', result: any, approval_id?: string, withdrawn: string[]}
 *   | {status: 'REFUSED', code: string|null, message: string, scenes: string[]}
 *   | {status: 'WAITING', approval_id?: string, message: string, withdrawn: string[]}} PressResult
 */

/**
 * One paid press, the same way for a step, a redo and the assembly: it is posted with the plan's
 * hash; when it raises the Owner's question (202) the page decides it APPROVED with his note, and
 * posts it again with the same body, which spends that yes. A refusal (409: a stale plan, an open
 * BLOCK, a short balance, the day's budget, scenes with no accepted take) stops it with the
 * backend's own reason, and nothing is decided. It never asks twice: a press that asks again after
 * his yes stops as WAITING.
 * @param {(path: string, options?: any) => Promise<any>} api
 * @param {string} path @param {any} body @param {{note?: string, commandId: string, purchaseId?: string}} o
 * @param {string} again what WAITING says
 * @returns {Promise<PressResult>}
 */
async function pressWithApproval(api, path, body, o, again) {
  // The press's own id (MONEY-04): the same press posted again (after his yes) is one purchase,
  // and the server answers a repeat with what it bought. Never his yes's id: the two are
  // different commands in the studio's record.
  const sent = o.purchaseId ? { ...body, command_id: o.purchaseId } : body;
  const post = () => api(path, { method: 'POST', body: JSON.stringify(sent), timeoutMs: STEP_TIMEOUT_MS });
  let first;
  try {
    first = await post();
  } catch (error) {
    return refused(error);
  }
  const withdrawn = Array.isArray(first?.withdrawn) ? first.withdrawn.map(String) : [];
  if (!asksOwner(first)) return { status: 'DONE', result: first, withdrawn };
  if (!first.approval_id) return { status: 'REFUSED', code: null, message: 'Studioul a cerut aprobarea fără o cerere de aprobat.', scenes: [] };
  try {
    const note = String(o.note || '').trim().slice(0, 500);
    await api(APPROVAL_DECISION_PATH, {
      method: 'POST',
      body: JSON.stringify(approvalDecisionCommand(first.approval_id, 'APPROVED', o.commandId, note || undefined)),
    });
  } catch (error) {
    return refused(error);
  }
  let second;
  try {
    second = await post();
  } catch (error) {
    return refused(error);
  }
  if (asksOwner(second)) return { status: 'WAITING', approval_id: second.approval_id, message: again, withdrawn };
  return { status: 'DONE', result: second, approval_id: first.approval_id, withdrawn };
}

/** @param {unknown} hash */
function isPlanHash(hash) {
  return /^[0-9a-f]{64}$/.test(String(hash || ''));
}

/**
 * The Owner's «Da, aprob și cumpăr» on one step, bound to the sheet's hash.
 * @param {(path: string, options?: any) => Promise<any>} api
 * @param {{storyboardId: string, step: string, planHash: string, note?: string, commandId: string, purchaseId?: string, allowOverBudget?: boolean}} o
 * @returns {Promise<{status: 'BOUGHT'|'REFUSED'|'WAITING', message?: string, code?: string|null, scenes?: string[], result?: any, approval_id?: string, withdrawn?: string[]}>}
 */
export async function approveStep(api, o) {
  if (!(/** @type {readonly string[]} */ (SHEET_STEPS)).includes(o.step)) throw new Error(`Pas necunoscut: ${o.step}`);
  if (!isPlanHash(o.planHash)) throw new Error('Amprenta nu este a unei foi de filmare; reîncarcă foaia.');
  const done = await pressWithApproval(
    api,
    stepPath(o.storyboardId, o.step),
    { plan_hash: o.planHash, allow_over_budget: Boolean(o.allowOverBudget) },
    o,
    'Aprobarea ta a fost scrisă, dar pasul o cere din nou: foaia s-a schimbat între timp. Reîncarcă foaia și privește-o din nou.',
  );
  return done.status === 'DONE' ? { ...done, status: 'BOUGHT' } : done;
}

/** @param {string} storyboardId */
export function redoPath(storyboardId) {
  return `/media/storyboards/${storyboardId}/redo`;
}

/**
 * The Owner's «Refă» on one scene (or the sound), bound to the redo plan's own hash. A still or a
 * motion redo buys, and goes through his yes like a step; a card or the sound costs nothing and is
 * one POST.
 * @param {(path: string, options?: any) => Promise<any>} api
 * @param {{storyboardId: string, kind: string, sceneIndex: number|null, planHash: string|null, note?: string, commandId: string, purchaseId?: string, allowOverBudget?: boolean}} o
 * @returns {Promise<PressResult>}
 */
export async function approveRedo(api, o) {
  if (!(/** @type {readonly string[]} */ (REDO_KINDS)).includes(o.kind)) throw new Error(`Refacere necunoscută: ${o.kind}`);
  const paid = PAID_REDOS.includes(o.kind);
  if (paid && !isPlanHash(o.planHash)) throw new Error('Refacerea nu are planul ei; reîncarcă foaia.');
  const note = String(o.note || '').trim().slice(0, 500);
  return pressWithApproval(
    api,
    redoPath(o.storyboardId),
    {
      kind: o.kind,
      scene_index: o.kind === 'audio' ? null : Number(o.sceneIndex),
      plan_hash: isPlanHash(o.planHash) ? o.planHash : null,
      note: note || null,
      allow_over_budget: Boolean(o.allowOverBudget),
    },
    o,
    'Aprobarea ta a fost scrisă, dar refacerea o cere din nou: planul ei s-a schimbat între timp. Reîncarcă foaia și privește-o din nou.',
  );
}

/**
 * The Owner's «Da, asamblează»: the film from its takes, its narration (asked under the same
 * sheet's hash when it has a price) and its QC.
 * @param {(path: string, options?: any) => Promise<any>} api
 * @param {{storyboardId: string, planHash: string, note?: string, commandId: string, purchaseId?: string, allowOverBudget?: boolean}} o
 * @returns {Promise<{status: 'ASSEMBLED'|'REFUSED'|'WAITING', message?: string, code?: string|null, scenes?: string[], result?: any, approval_id?: string, withdrawn?: string[]}>}
 */
export async function approveAssemble(api, o) {
  if (!isPlanHash(o.planHash)) throw new Error('Amprenta nu este a unei foi de filmare; reîncarcă foaia.');
  const done = await pressWithApproval(
    api,
    stepPath(o.storyboardId, ASSEMBLE_STEP),
    { plan_hash: o.planHash, allow_over_budget: Boolean(o.allowOverBudget) },
    o,
    'Aprobarea ta a fost scrisă, dar asamblarea o cere din nou: foaia s-a schimbat între timp. Reîncarcă foaia și privește-o din nou.',
  );
  return done.status === 'DONE' ? { ...done, status: 'ASSEMBLED' } : done;
}
