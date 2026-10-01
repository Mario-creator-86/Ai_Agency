import { APPROVAL_DECISION_PATH, approvalDecisionCommand } from './governance.js';
import { paidMediaRuleWords } from './owner_controls.js';

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
 * This module is pure (no DOM, no fetch): main.js paints its HTML and passes its api().
 */

/** The drawer's name. */
export const SHEET_TITLE = 'Foaia de filmare';

/** The three paid steps, in the order they are bought (backend SHEET_STEPS). */
export const SHEET_STEPS = /** @type {const} */ (['stills', 'test_shot', 'motion']);

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

/** The shot sizes the prompt compiler writes into a still prompt, and the word the sheet uses. */
const FRAME_WORDS = /** @type {const} */ ([
  [/\b(detail|details|close-up|close up|closeup|macro|hands)\b/i, 'Detaliu'],
  [/\bmedium\b/i, 'Plan mediu'],
  [/\b(wide|establishing|aerial|landscape|panorama|vista)\b/i, 'Peisaj'],
]);

/**
 * What the camera frames in a scene, in one word: the shot size its still prompt names (the
 * earliest one wins), or the card's kind. Words only: nothing is decided from it.
 * @param {any} scene a sheet scene
 */
export function frameWord(scene) {
  const kind = String(scene?.kind || 'LIVE');
  if (kind in COMPOSED_WORDS) return COMPOSED_WORDS[/** @type {keyof typeof COMPOSED_WORDS} */ (kind)];
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

/** The label of a LIVE scene's still redo; '' where there is no approved still to redo. @param {any} scene */
export function stillRedoLabel(scene) {
  if (isCard(scene) || !scene?.still) return '';
  return `Refă imaginea (${creditWords(scene.still_credits)})`;
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

/**
 * The step buttons: label, price and cap, and every Romanian reason it cannot be pressed now.
 * @param {any} sheet
 * @returns {{step: string, label: string, price_ro: string, cap_ro: string, to_buy: number[], disabled: boolean, reasons: string[], reason_ro: string, over_budget: boolean, over_budget_ro: string}[]}
 */
export function stepButtons(sheet) {
  const footer = sheet?.footer || {};
  const gaps = Array.isArray(sheet?.shot_plan_gaps) ? sheet.shot_plan_gaps : [];
  const hero = heroState(sheet);
  return SHEET_STEPS.map((name) => {
    const step = (sheet?.steps && sheet.steps[name]) || {};
    const toBuy = Array.isArray(step.to_buy) ? step.to_buy.map(Number) : [];
    const cap = Number(step.cap_credits) || 0;
    /** @type {string[]} */
    const reasons = [];
    if (sheet?.lint_blocked) reasons.push(`Blocaj deschis: ${sheet.lint_summary_ro || 'prompturile au blocaje.'}`);
    if (gaps.length) reasons.push(`Scenele ${gaps.join(', ')} nu au planul de cadre scris de model; filmul așteaptă planul de cadre.`);
    if (!toBuy.length) reasons.push(String(step.waiting_ro || 'Nu este nimic de cumpărat la acest pas.'));
    if (name === 'motion' && hero.scene !== null && !hero.approved) {
      reasons.push(hero.bought
        ? `Cadrul de probă (scena ${hero.scene}) așteaptă privirea ta: aprobă-l pe foaie înainte de restul mișcării.`
        : `Întâi cadrul de probă (scena ${hero.scene}): restul mișcării se cumpără abia după ce îl vezi și îl aprobi.`);
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
    { key: 'saved', label: 'Economie', value: `${money(f.saved_credits, f.saved_usd_micros)} față de seedance2_5 peste tot` },
    { key: 'source', label: 'Sursa prețurilor', value: String(f.price_source || 'necunoscută') },
    { key: 'balance', label: 'Sold Runway', value: balance.credits === null || balance.credits === undefined ? `necitit (${balance.problem || 'necunoscut'})` : creditWords(Number(balance.credits)) },
    { key: 'daily', label: 'Bugetul zilei', value: daily ? `${usdText(micros(daily.remaining_usd))} rămași din ${usdText(micros(daily.limit_usd))}` : 'fără buget zilnic citit' },
    { key: 'alternatives', label: 'Alternative', value: alternatives.join('; ') || 'niciuna cu preț publicat' },
    { key: 'hash', label: 'Amprenta foii', value: String(f.sheet_hash || sheet?.sheet_hash || '').slice(0, 12) },
  ];
}

/* ------------------------------------------------------------------------------- the markup */

/**
 * @typedef {{escape: (value: unknown) => string, confirm?: string|null, notice?: string, noticeError?: boolean}} SheetOptions
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
  const why = take?.reason_ro || take?.failure_code;
  return `<span class="sheet-take-status" data-status="${e(take?.status)}">${e(status)}</span>${why ? `<span class="sheet-take-why">: ${e(why)}</span>` : ''}`;
}

/** @param {(value: unknown) => string} e @param {any} scene */
function liveSceneHtml(e, scene) {
  const m = scene.motion || {};
  const index = scene.scene_index;
  const still = scene.still
    ? `<figure class="sheet-still-box"><img class="sheet-still" data-sheet-src="${e(scene.still.file_url)}" alt="Imaginea aprobată a scenei ${e(index)}"><figcaption>Aprobată de ${e(scene.still.approved_by || '—')} · ${e(scene.still.model_id || '')}</figcaption></figure>`
    : '<p class="sheet-still-missing">Nicio imagine aprobată încă: scena intră în pasul imaginilor.</p>';
  const redo = stillRedoLabel(scene)
    ? `<button type="button" class="quiet sheet-redo" data-sheet-action="redo-still" data-take="${e(scene.still.take_id)}" data-scene="${e(index)}">${e(stillRedoLabel(scene))}</button>`
    : '';
  const candidates = (Array.isArray(scene.candidates) ? scene.candidates : []).map((/** @type {any} */ c) => `<li class="sheet-candidate">`
    + (c.file_url ? `<img class="sheet-thumb" data-sheet-src="${e(c.file_url)}" alt="Candidat pentru scena ${e(index)}">` : '')
    + `<p>${takeWords(e, c)}</p>${takeButtons(e, c, 'still')}</li>`).join('');
  const shots = (Array.isArray(scene.shots) ? scene.shots : []).map((/** @type {any} */ s) => `<li class="sheet-shot">`
    + `<p>${s.kind === 'test_shot' ? 'Cadrul de probă' : 'Clip'} · ${e(s.model_id || '—')} · ${e(s.seconds ?? '?')} s · ${takeWords(e, s)}</p>`
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
  return `${still}${redo}`
    + `${why}${choices.length ? `<div class="sheet-models">${choices.join('')}</div>` : ''}`
    + `<p class="sheet-still-price">Imaginea: ${e(creditWords(scene.still_credits))} (${e(scene.still_price_source || 'fără preț')}) · sămânța ${e(m.seed ?? '—')}</p>`
    + (badges ? `<ul class="sheet-badges">${badges}</ul>` : '')
    + `<p class="sheet-lint">Verificarea prompturilor: <strong class="${lint === 'curat' ? 'sheet-ok' : 'sheet-warn'}">${e(lint)}</strong></p>`
    + (findings ? `<ul class="sheet-findings">${findings}</ul>` : '')
    + `<details class="sheet-prompt"><summary>Vezi promptul imaginii</summary><p lang="en">${e(scene.still_prompt)}</p></details>`
    + `<details class="sheet-prompt"><summary>Vezi promptul de mișcare</summary><p lang="en">${e(scene.motion_prompt)}</p>`
    + (scene.negative_prompt ? `<p class="sheet-negative">Prompt negativ: <span lang="en">${e(scene.negative_prompt)}</span></p>` : '')
    + '</details>'
    + (candidates ? `<p class="sheet-sub">Alte imagini</p><ul class="sheet-candidates">${candidates}</ul>` : '')
    + (shots ? `<p class="sheet-sub">Clipuri cumpărate</p><ul class="sheet-shots">${shots}</ul>` : '');
}

/** @param {(value: unknown) => string} e @param {any} scene */
function cardSceneHtml(e, scene) {
  const card = scene.card || {};
  const spec = card.card_json || {};
  const bars = (Array.isArray(spec.bars) ? spec.bars : []).map((/** @type {any} */ b) => `<li>${e(b.label)}: ${e(cardValue(b.value))} ${e(b.unit)}</li>`).join('');
  return (card.preview_url ? `<figure class="sheet-still-box"><img class="sheet-still" data-sheet-src="${e(card.preview_url)}" alt="Previzualizarea scenei ${e(scene.scene_index)}, compusă local"></figure>` : '')
    + (spec.title ? `<p class="sheet-card-title">${e(spec.title)}</p>` : '')
    + (bars ? `<ul class="sheet-card-bars">${bars}</ul>` : '')
    + (spec.cta ? `<p class="sheet-card-cta">${e(spec.cta)}</p>` : '')
    + (card.problem_ro ? `<p class="sheet-problem">${e(card.problem_ro)}</p>` : '')
    + `<p class="sheet-why">${e(COMPOSED_WHY[/** @type {keyof typeof COMPOSED_WHY} */ (scene.kind)] || COMPOSED_WHY.DATA_CARD)}</p>`;
}

/**
 * The question a step's button opens: what is bought, its price and cap, the sheet it is bound to,
 * the daily budget's consent when it is needed, and his note. '' when the step cannot be pressed.
 * @param {any} sheet @param {string} step @param {SheetOptions} o
 */
export function stepConfirmHtml(sheet, step, o) {
  const e = o.escape;
  const b = stepButtons(sheet).find((x) => x.step === step);
  if (!b || b.disabled) return '';
  const scenes = b.to_buy.length === 1 ? `Scena ${b.to_buy[0]}` : `Scenele ${b.to_buy.join(', ')}`;
  const hash = String(sheet.sheet_hash || '').slice(0, 12);
  return `<div class="sheet-confirm" role="group" aria-label="${e(b.label)}">`
    + `<p class="sheet-confirm-q">${e(STEP_QUESTIONS[/** @type {keyof typeof STEP_QUESTIONS} */ (step)])}</p>`
    + `<p>${e(scenes)} · ${e(b.price_ro)} · ${e(b.cap_ro)}.</p>`
    + `<p class="sheet-confirm-bind">Aprobarea ta se leagă de această foaie (${e(hash)}): dacă foaia se schimbă, ea nu mai cumpără nimic.</p>`
    + (b.over_budget
      ? `<label class="sheet-over"><input type="checkbox" data-sheet-over-budget> ${e(b.over_budget_ro)} Bifează doar dacă vrei să depășești bugetul pentru acest pas.</label>`
      : '')
    + '<label class="sheet-note">Nota ta (opțional)<textarea data-sheet-note maxlength="500" rows="2"></textarea></label>'
    + `<div class="sheet-confirm-actions"><button type="button" class="sheet-yes" data-sheet-action="confirm-step" data-step="${e(step)}">Da, aprob și cumpăr</button>`
    + '<button type="button" class="quiet" data-sheet-action="cancel-step">Nu acum</button></div>'
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
  const head = '<header class="sheet-head">'
    + `<p class="eyebrow sheet-eyebrow">${e(SHEET_TITLE)} · 0 credite</p>`
    + `<h2 class="sheet-title">${e(sheet?.title || '')}</h2>`
    + `<p class="sheet-rule">${e(paidMediaRuleWords(sheet?.owner_rule))}</p>`
    + `<p class="sheet-meta">Rezoluție ${e(sheet?.resolution || '—')} · sămânța filmului ${e(sheet?.seed ?? '—')} · foaia ${e(hash)}</p>`
    + (sheet?.reference_images_verified === false
      ? '<p class="sheet-flag">Imaginile scenelor 2 și următoarele folosesc imaginea scenei 1 ca referință (lumină, paletă, granulație). Pe acest cont efectul este încă nevalidat, până la primul pas aprobat.</p>'
      : '')
    + (gaps.length ? `<p class="sheet-flag sheet-blocked">Scenele ${e(gaps.join(', '))} nu au planul de cadre scris de model; filmul așteaptă planul de cadre.</p>` : '')
    + (sheet?.lint_summary_ro ? `<p class="sheet-lint-summary${sheet?.lint_blocked ? ' sheet-blocked' : ''}">${e(sheet.lint_summary_ro)}</p>` : '')
    + (blocks ? `<ul class="sheet-findings sheet-blocked">${blocks}</ul>` : '')
    + (o.notice ? `<p class="sheet-notice${o.noticeError ? ' sheet-blocked' : ''}" role="status">${e(o.notice)}</p>` : '')
    + '</header>';
  const list = scenes.map((/** @type {any} */ scene) => `<li class="sheet-scene" data-kind="${e(scene.kind)}">`
    + `<h3 class="sheet-scene-line">${e(sceneLine(scene))}</h3>`
    + (scene.narration ? `<p class="sheet-narration">«${e(scene.narration)}»</p>` : '')
    + (isCard(scene) ? cardSceneHtml(e, scene) : liveSceneHtml(e, scene))
    + '</li>').join('');
  const rows = footerRows(sheet).map((r) => `<div class="sheet-row" data-key="${e(r.key)}"><dt>${e(r.label)}</dt><dd>${e(r.value)}</dd></div>`).join('');
  const steps = stepButtons(sheet).map((b) => '<div class="sheet-step-box">'
    + `<button type="button" class="sheet-step" data-sheet-action="step" data-step="${e(b.step)}"${b.disabled ? ' disabled' : ''}>${e(b.label)}</button>`
    + `<span class="sheet-step-price">${e(b.price_ro)} · ${e(b.cap_ro)}</span>`
    + (b.reason_ro ? `<p class="sheet-step-why">${e(b.reason_ro)}</p>` : '')
    + (b.over_budget && !b.disabled ? `<p class="sheet-step-warn">${e(b.over_budget_ro)}</p>` : '')
    + (o.confirm === b.step ? stepConfirmHtml(sheet, b.step, o) : '')
    + '</div>').join('');
  return `${head}<ol class="sheet-scenes">${list}</ol>`
    + `<footer class="sheet-footer"><dl class="sheet-rows">${rows}</dl>`
    + (sheet?.footer?.summary_ro ? `<p class="sheet-summary">${e(sheet.footer.summary_ro)}</p>` : '')
    + `<div class="sheet-steps">${steps}</div></footer>`;
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

/** @param {any} body */
function asksOwner(body) {
  return Boolean(body && body.status === 'NEEDS_APPROVAL');
}

/** @param {any} error */
function refused(error) {
  const detail = error && error.detail;
  if (detail && typeof detail === 'object') {
    return { status: 'REFUSED', code: detail.status || detail.error || null, message: String(detail.message || error.message || '') };
  }
  return { status: 'REFUSED', code: null, message: String((error && error.message) || detail || '') };
}

/**
 * The Owner's «Da, aprob și cumpăr» on one step: the step is posted with the sheet's hash; when it
 * raises his question (202) the page decides it APPROVED with his note, and posts the step again
 * with the same hash, which spends that yes and buys. A 409 (stale sheet, open BLOCK, short
 * balance, the day's budget) stops it with the backend's own reason, and nothing is decided. It
 * never asks twice: a step that asks again after his yes stops as WAITING.
 * @param {(path: string, options?: any) => Promise<any>} api
 * @param {{storyboardId: string, step: string, planHash: string, note?: string, commandId: string, allowOverBudget?: boolean}} o
 * @returns {Promise<{status: 'BOUGHT'|'REFUSED'|'WAITING', message?: string, code?: string|null, result?: any, approval_id?: string}>}
 */
export async function approveStep(api, o) {
  if (!(/** @type {readonly string[]} */ (SHEET_STEPS)).includes(o.step)) throw new Error(`Pas necunoscut: ${o.step}`);
  if (!/^[0-9a-f]{64}$/.test(String(o.planHash || ''))) throw new Error('Amprenta nu este a unei foi de filmare; reîncarcă foaia.');
  const post = () => api(stepPath(o.storyboardId, o.step), {
    method: 'POST',
    body: JSON.stringify({ plan_hash: o.planHash, allow_over_budget: Boolean(o.allowOverBudget) }),
    timeoutMs: STEP_TIMEOUT_MS,
  });
  let first;
  try {
    first = await post();
  } catch (error) {
    return /** @type {any} */ (refused(error));
  }
  if (!asksOwner(first)) return { status: 'BOUGHT', result: first };
  if (!first.approval_id) return { status: 'REFUSED', code: null, message: 'Studioul a cerut aprobarea fără o cerere de aprobat.' };
  try {
    const note = String(o.note || '').trim().slice(0, 500);
    await api(APPROVAL_DECISION_PATH, {
      method: 'POST',
      body: JSON.stringify(approvalDecisionCommand(first.approval_id, 'APPROVED', o.commandId, note || undefined)),
    });
  } catch (error) {
    return /** @type {any} */ (refused(error));
  }
  let second;
  try {
    second = await post();
  } catch (error) {
    return /** @type {any} */ (refused(error));
  }
  if (asksOwner(second)) {
    return {
      status: 'WAITING',
      approval_id: second.approval_id,
      message: 'Aprobarea ta a fost scrisă, dar pasul o cere din nou: foaia s-a schimbat între timp. Reîncarcă foaia și privește-o din nou.',
    };
  }
  return { status: 'BOUGHT', result: second, approval_id: first.approval_id };
}
