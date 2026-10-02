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

/** The margin over a step's cap the Runway balance must hold (backend BALANCE_MARGIN). */
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
};

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
  return `${frame} · ${m.model_id} · ${m.resolution || '—'} · ${m.billed_seconds ?? '?'} s · ${creditWords(m.credits)}`;
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
 *   replaces: string[], invalidates: string[]}} RedoButton
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
      const neededRaw = footer.balance_needed_credits ? footer.balance_needed_credits[name] : undefined;
      const needed = Number.isFinite(Number(neededRaw)) ? Number(neededRaw) : Math.ceil(cap * BALANCE_MARGIN);
      if (balance.credits === null || balance.credits === undefined || !Number.isFinite(Number(balance.credits))) {
        reasons.push(`Soldul Runway nu a putut fi citit (${balance.problem || 'necunoscut'}); nimic nu se cumpără pe un sold necunoscut.`);
      } else if (Number(balance.credits) < needed) {
        reasons.push(`Sold Runway insuficient: ${creditWords(Number(balance.credits))}; pasul cere plafonul de ${creditWords(cap)} plus marja de 15% (${creditWords(needed)}).`);
      }
    }
    const daily = footer.daily_budget;
    const capUsd = Number(step.cap_usd);
    const overBudget = Boolean(toBuy.length && daily && Number.isFinite(capUsd) && Number.isFinite(Number(daily.remaining_usd)) && capUsd > Number(daily.remaining_usd));
    return {
      step: name,
      label: STEP_LABELS[name],
      price_ro: `${creditWords(step.cost_credits ?? 0)} (${usdText(micros(step.cost_usd ?? 0))})`,
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
  const busy = inProgressReason(sheet);
  if (busy) reasons.push(busy);
  else if (step.in_progress) reasons.push('Asamblarea este deja în curs; foaia se reîncarcă singură când se termină.');
  const left = (Array.isArray(step.paid_steps_left) ? step.paid_steps_left : []).map((/** @type {string} */ s) => STEP_WORDS[/** @type {keyof typeof STEP_WORDS} */ (s)] || s);
  if (left.length) reasons.push(`Întâi pașii plătiți rămași: ${left.join(', ')}. Filmul se asamblează după ultimul.`);
  for (const b of Array.isArray(step.blocked) ? step.blocked : []) if (b && b.reason_ro) reasons.push(String(b.reason_ro));
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
    { key: 'balance', label: 'Sold Runway', value: balance.credits === null || balance.credits === undefined ? `necitit (${balance.problem || 'necunoscut'})` : creditWords(Number(balance.credits)) },
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

/* ------------------------------------------------------------------------------- the markup */

/**
 * @typedef {{escape: (value: unknown) => string, confirm?: string|null, notice?: string,
 *   noticeError?: boolean, policy?: any, assembled?: any, ruleOpen?: boolean}} SheetOptions
 */

/** @param {(value: unknown) => string} e @param {any} take @param {string} what */
function takeButtons(e, take, what) {
  if (!take || take.status !== 'PAID') return '';
  const approve = what === 'shot' && take.kind === 'test_shot' ? 'Aprobă cadrul de probă după ce l-ai văzut' : what === 'shot' ? 'Aprobă cadrul' : 'Alege imaginea aceasta';
  const reject = what === 'shot' ? 'Respinge cadrul' : 'Respinge';
  return `<div class="sheet-take-actions">`
    + `<button type="button" class="quiet sheet-take-btn" data-sheet-action="take" data-take="${e(take.take_id)}" data-decision="APPROVED">${e(approve)}</button>`
    + `<button type="button" class="quiet sheet-take-btn" data-sheet-action="take" data-take="${e(take.take_id)}" data-decision="REJECTED">${e(reject)}</button>`
    + '</div>';
}

/** @param {(value: unknown) => string} e @param {any} take */
function takeWords(e, take) {
  const status = TAKE_WORDS[/** @type {keyof typeof TAKE_WORDS} */ (take?.status)] || String(take?.status || '');
  let why = take?.reason_ro || take?.failure_code;
  // a shot the clip QC rejected says why on its own line (clipQcWords), not twice
  if (take?.clip_qc && String(take?.reason_ro || '').startsWith('Controlul clipului')) why = '';
  return `<span class="sheet-take-status" data-status="${e(take?.status)}">${e(status)}</span>${why ? `<span class="sheet-take-why">: ${e(why)}</span>` : ''}`;
}

/**
 * The question a «Refă» press opens: what it redoes and replaces, its price and cap, the plan it is
 * bound to, the day's budget consent when needed, and his note. '' when it cannot be pressed.
 * @param {any} sheet @param {string|null|undefined} key redoKey(kind, scene) @param {SheetOptions} o
 */
export function redoConfirmHtml(sheet, key, o) {
  const e = o.escape;
  const b = redoFor(sheet, key);
  if (!b || b.disabled) return '';
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
  const rows = buttons.map((b) => '<div class="sheet-redo-box">'
    + `<button type="button" class="quiet sheet-redo-btn" data-sheet-action="redo" data-kind="${e(b.kind)}" data-scene="${e(b.scene ?? '')}" title="${e(b.reason_ro)}"${b.disabled ? ' disabled' : ''}>${e(b.label)}</button>`
    + `<span class="sheet-redo-price">${e(b.cap_ro ? `${b.price_ro} · ${b.cap_ro}` : b.price_ro)}</span>`
    + (b.disabled && b.reason_ro ? `<p class="sheet-step-why">${e(b.reason_ro)}</p>` : '')
    // the sound's plan is one short sentence (what it remasters, or that there is no film yet)
    + (!b.disabled && b.kind === 'audio' && b.reason_ro ? `<p class="sheet-redo-why">${e(b.reason_ro)}</p>` : '')
    + '</div>').join('');
  const open = buttons.map((b) => redoKey(b.kind, b.scene)).includes(String(o.confirm || '')) ? redoConfirmHtml(sheet, o.confirm, o) : '';
  return `<div class="sheet-redos"><p class="sheet-sub">${e(title)}</p>${rows}${open}</div>`;
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
  const still = scene.still
    ? `<figure class="sheet-still-box"><img class="sheet-still" data-sheet-src="${e(scene.still.file_url)}" alt="Imaginea aprobată a scenei ${e(index)}"><figcaption>Aprobată de ${e(scene.still.approved_by || '—')} · ${e(scene.still.model_id || '')}</figcaption></figure>`
    : '<p class="sheet-still-missing">Nicio imagine aprobată încă: scena intră în pasul imaginilor.</p>';
  const candidates = (Array.isArray(scene.candidates) ? scene.candidates : []).map((/** @type {any} */ c) => `<li class="sheet-candidate">`
    + (c.file_url ? `<img class="sheet-thumb" data-sheet-src="${e(c.file_url)}" alt="Candidat pentru scena ${e(index)}">` : '')
    + `<p>${takeWords(e, c)}</p>${takeButtons(e, c, 'still')}</li>`).join('');
  const shots = (Array.isArray(scene.shots) ? scene.shots : []).map((/** @type {any} */ s) => `<li class="sheet-shot">`
    + `<p>${s.kind === 'test_shot' ? 'Cadrul de probă' : 'Clip'} · ${e(s.model_id || '—')} · ${e(s.seconds ?? '?')} s · ${takeWords(e, s)}</p>`
    + `<p class="sheet-clip-qc" data-verdict="${e(s.clip_qc?.verdict || 'NONE')}">${e(clipQcWords(s.clip_qc))}</p>`
    + (s.file_url ? `<button type="button" class="quiet sheet-play" data-sheet-action="play" data-sheet-src="${e(s.file_url)}">Redă clipul</button>` : '')
    + `${takeButtons(e, s, 'shot')}</li>`).join('');
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
  return still
    + `${why}${safetyHtml(e, scene)}${choices.length ? `<div class="sheet-models">${choices.join('')}</div>` : ''}`
    + `<p class="sheet-still-price">Imaginea: ${e(creditWords(scene.still_credits))} (${e(scene.still_price_source || 'fără preț')}) · sămânța ${e(m.seed ?? '—')}</p>`
    + (badges ? `<ul class="sheet-badges">${badges}</ul>` : '')
    + `<p class="sheet-lint">Verificarea prompturilor: <strong class="${lint === 'curat' ? 'sheet-ok' : 'sheet-warn'}">${e(lint)}</strong></p>`
    + (findings ? `<ul class="sheet-findings">${findings}</ul>` : '')
    + `<details class="sheet-prompt"><summary>Vezi promptul imaginii</summary><p lang="en">${e(scene.still_prompt)}</p></details>`
    + `<details class="sheet-prompt"><summary>Vezi promptul de mișcare</summary><p lang="en">${e(scene.motion_prompt)}</p>`
    + (scene.negative_prompt ? `<p class="sheet-negative">Prompt negativ: <span lang="en">${e(scene.negative_prompt)}</span></p>` : '')
    + '</details>'
    + (candidates ? `<p class="sheet-sub">Alte imagini</p><ul class="sheet-candidates">${candidates}</ul>` : '')
    + (shots ? `<p class="sheet-sub">Clipuri cumpărate</p><ul class="sheet-shots">${shots}</ul>` : '')
    + redoBlockHtml(sheet, redoButtons(scene), 'Refă doar această scenă', o);
}

/** @param {any} sheet @param {any} scene @param {SheetOptions} o */
function cardSceneHtml(sheet, scene, o) {
  const e = o.escape;
  const card = scene.card || {};
  const spec = card.card_json || {};
  const bars = (Array.isArray(spec.bars) ? spec.bars : []).map((/** @type {any} */ b) => `<li>${e(b.label)}: ${e(cardValue(b.value))} ${e(b.unit)}</li>`).join('');
  return (card.preview_url ? `<figure class="sheet-still-box"><img class="sheet-still" data-sheet-src="${e(card.preview_url)}" alt="Previzualizarea scenei ${e(scene.scene_index)}, compusă local"></figure>` : '')
    + (spec.title ? `<p class="sheet-card-title">${e(spec.title)}</p>` : '')
    + (bars ? `<ul class="sheet-card-bars">${bars}</ul>` : '')
    + (spec.cta ? `<p class="sheet-card-cta">${e(spec.cta)}</p>` : '')
    + (card.problem_ro ? `<p class="sheet-problem">${e(card.problem_ro)}</p>` : '')
    + `<p class="sheet-why">${e(COMPOSED_WHY[/** @type {keyof typeof COMPOSED_WHY} */ (scene.kind)] || COMPOSED_WHY.DATA_CARD)}</p>`
    + redoBlockHtml(sheet, redoButtons(scene), 'Refă doar această scenă', o);
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

/** The bar at the top of the drawer (sticky while he scrolls the scenes). @param {any} sheet @param {SheetOptions} o */
function sheetSummaryHtml(sheet, o) {
  const e = o.escape;
  const summary = sheetSummary(sheet, o.policy || null);
  const next = summary.next;
  const busy = inProgressReason(sheet);
  return '<div class="sheet-summary-bar" role="region" aria-label="Pe scurt">'
    + `<p class="sheet-summary-rule">${e(summary.rule_ro)}</p>`
    + (next
      ? `<p class="sheet-summary-next">Următorul pas: <strong>${e(next.label)}</strong> · ${e(next.price_ro)}${next.cap_ro ? ` · ${e(next.cap_ro)}` : ''}${next.disabled ? ` <span class="sheet-summary-why">— ${e(busy || next.reason_ro)}</span>` : ''}</p>`
      : '')
    + '<button type="button" class="quiet sheet-summary-go" data-sheet-action="to-steps">Mergi la pași</button>'
    + '</div>';
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
    + `<p class="eyebrow sheet-eyebrow">${e(SHEET_TITLE)} · 0 credite</p>`
    + `<h2 class="sheet-title">${e(sheet?.title || '')}</h2>`
    + `<div class="sheet-rule-line"><p class="sheet-rule">${e(paidMediaRuleWords(rule))}</p>`
    + `<details class="sheet-rule-box"${o.ruleOpen ? ' open' : ''}><summary>Schimbă regula</summary>${paidMediaFormHtml(o.policy || null, o)}</details></div>`
    + `<p class="sheet-meta">Rezoluție ${e(sheet?.resolution || '—')} · sămânța filmului ${e(sheet?.seed ?? '—')} · foaia ${e(hash)}</p>`
    + (sheet?.reference_images_verified === false
      ? '<p class="sheet-flag">Imaginile scenelor 2 și următoarele folosesc imaginea scenei 1 ca referință (lumină, paletă, granulație). Pe acest cont efectul este încă nevalidat, până la primul pas aprobat.</p>'
      : '')
    + (problem ? `<p class="sheet-flag sheet-blocked">Lista ta de modele (config/film_models.json) nu a putut fi citită: ${e(problem)}</p>` : '')
    + (gaps.length ? `<p class="sheet-flag sheet-blocked">Scenele ${e(gaps.join(', '))} nu au planul de cadre scris de model; filmul așteaptă planul de cadre.</p>` : '')
    + (sheet?.lint_summary_ro ? `<p class="sheet-lint-summary${sheet?.lint_blocked ? ' sheet-blocked' : ''}">${e(sheet.lint_summary_ro)}</p>` : '')
    + (blocks ? `<ul class="sheet-findings sheet-blocked">${blocks}</ul>` : '')
    + (o.notice ? `<p class="sheet-notice${o.noticeError ? ' sheet-blocked' : ''}" role="status">${e(o.notice)}</p>` : '')
    + '</header>';
  const list = scenes.map((/** @type {any} */ scene) => `<li class="sheet-scene" data-kind="${e(scene.kind)}">`
    + `<h3 class="sheet-scene-line">${e(sceneLine(scene))}</h3>`
    + (scene.narration ? `<p class="sheet-narration">«${e(scene.narration)}»</p>` : '')
    + (isCard(scene) ? cardSceneHtml(sheet, scene, o) : liveSceneHtml(sheet, scene, o))
    + '</li>').join('');
  const rows = footerRows(sheet).map((r) => `<div class="sheet-row" data-key="${e(r.key)}"><dt>${e(r.label)}</dt><dd>${e(r.value)}</dd></div>`).join('');
  const steps = stepButtons(sheet).map((b) => '<div class="sheet-step-box">'
    + `<button type="button" class="sheet-step" data-sheet-action="step" data-step="${e(b.step)}"${b.disabled ? ' disabled' : ''}>${e(b.label)}</button>`
    + `<span class="sheet-step-price">${e(b.price_ro)} · ${e(b.cap_ro)}</span>`
    + (b.reason_ro ? `<p class="sheet-step-why">${e(b.reason_ro)}</p>` : '')
    + (b.over_budget && !b.disabled ? `<p class="sheet-step-warn">${e(b.over_budget_ro)}</p>` : '')
    + (o.confirm === b.step ? stepConfirmHtml(sheet, b.step, o) : '')
    + '</div>').join('');
  const a = assembleButton(sheet);
  const assemble = '<div class="sheet-step-box sheet-assemble">'
    + `<button type="button" class="sheet-step" data-sheet-action="step" data-step="${e(ASSEMBLE_STEP)}"${a.disabled ? ' disabled' : ''}>${e(a.label)}</button>`
    + `<span class="sheet-step-price">${e(a.price_ro)}</span>`
    + (a.line_ro ? `<p class="sheet-assemble-line">${e(a.line_ro)}</p>` : '')
    + (a.reason_ro ? `<p class="sheet-step-why">${e(a.reason_ro)}</p>` : '')
    + (o.confirm === ASSEMBLE_STEP ? stepConfirmHtml(sheet, ASSEMBLE_STEP, o) : '')
    + assembleResultHtml(o.assembled, o)
    + '</div>';
  const sound = audioRedoButton(sheet);
  return `${sheetSummaryHtml(sheet, o)}${head}<ol class="sheet-scenes">${list}</ol>`
    + `<footer class="sheet-footer" id="sheet-steps"><dl class="sheet-rows">${rows}</dl>`
    + (sheet?.footer?.summary_ro ? `<p class="sheet-summary">${e(sheet.footer.summary_ro)}</p>` : '')
    + `<div class="sheet-steps">${steps}${assemble}</div>`
    + (sound ? `<div class="sheet-redo-audio">${redoBlockHtml(sheet, [sound], 'Sunetul filmului', o)}</div>` : '')
    + '</footer>';
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
