import { approvalDecisionCommand } from './governance.js';
import { when } from './mail_thread.js';
import { resolveCommand } from './owner_inbox.js';
import { countWords } from './plurals.js';
import { sheetKeyFor } from './sheet_key.js';

/**
 * «DECIZII» — THE OWNER'S OWN WINDOW OF DECISIONS (DECISIONS_WINDOW, 2026-10-03).
 *
 * His words: «Dacă sunt decizii pe care eu ca owner trebuie să le iau, trebuie să îmi apară un
 * card. Trebuie să am propria mea fereastră unde pot să accept sau refuz ce îmi este recomandat
 * sau trimis.» GET /owner/decision-cards (app.decisions) answers every question that waits for
 * him as one kind of card: a paid step (an approval), a recommendation of an agent, a stage or
 * the audit (a decision), a letter that asks him something. This module reads that feed, draws
 * each card and sends his answer to the route the card names: a decision to its own decide
 * route (his accept is applied there through his own Owner command), an approval to the existing
 * approvals route, a letter to its reply and resolve routes. Nothing is decided here; only his
 * key, through his press, answers a card.
 *
 * Pure: no DOM, so node --test loads it. decisions_window.js draws it in its dialog.
 */

/** Where the window reads its cards (behind his key). */
export const DECISION_CARDS_PATH = '/owner/decision-cards';

/** The three kinds of card the feed answers with. */
const SOURCE_TYPES = ['decision', 'approval', 'letter'];

/** Option types whose accept spends money or changes his policy: they ask once more. */
const ASK_FIRST_TYPES = ['budget', 'paid_media_approval', 'environment', 'autonomy_mode'];

/** The Owner commands an accept runs, as the history says them (app.decisions APPLIERS). */
const COMMAND_WORDS = /** @type {Record<string, string>} */ ({
  SpendingBudget: 'bugetul',
  SetPaidMediaApproval: 'regula pașilor plătiți',
  SetEnvironment: 'mediul studioului',
  SetAutonomyMode: 'modul de autonomie',
});

/** The same, by the option's type, when the answer carries no command name. */
const TYPE_WORDS = /** @type {Record<string, string>} */ ({
  budget: 'bugetul',
  paid_media_approval: 'regula pașilor plătiți',
  environment: 'mediul studioului',
  autonomy_mode: 'modul de autonomie',
});

/** The Settings tabs a guided card can send him to (app.wording.SETTINGS_TABS). */
const SETTINGS_PLACES = /** @type {Record<string, string>} */ ({
  llm: 'Setări → Furnizori AI',
  agents: 'Setări → Angajați',
  media: 'Setări → Video și sunet',
  social: 'Setări → Conturi și e-mail',
  channels: 'Setări → Canale',
});

/** Who proposes, in his words: the employees by their role. */
const ROLE_WORDS = /** @type {Record<string, string>} */ ({
  director: 'Directoarea',
  researcher: 'Cercetătorul',
  accountant: 'Contabilul',
  video_editor: 'Editorul video',
  videoeditor: 'Editorul video',
  scriptwriter: 'Scenaristul',
  publisher: 'Publicistul',
});

/** A paid step, as the card says it. */
const STEP_WORDS = /** @type {Record<string, string>} */ ({
  stills: 'imaginile',
  test_shot: 'cadrul de probă',
  motion: 'mișcarea',
  scene_redo: 'o refacere',
  assemble: 'narațiunea',
});

/**
 * @typedef {{key: string, label_ro: string, effect_ro: string, recommended: boolean, apply_type: string,
 *   place_ro: string|null, steps_ro: string|null, place?: string|null}} CardOption
 * @typedef {{card_id: string, source_type: string, id: string, kind: string, subject: any, title_ro: string,
 *   why_ro: string, effect_ro: string, options: CardOption[], recommended_option: string|null, source: string,
 *   status: string, status_ro: string, chosen_option: string|null, note: string|null, decided_by: string|null,
 *   decided_at: string|null, applied: any, apply_error_ro: string|null, expires_at: string|null,
 *   version: number|null, created_at: string, updated_at: string, waiting: boolean, answer: any,
 *   context: any, cost_usd: number|null}} DecisionCard
 * @typedef {{approvals: number, decisions: number, waiting_action: number, letters: number}} DecisionCounts
 * @typedef {{cards: DecisionCard[], history: DecisionCard[], count: number, counts: DecisionCounts,
 *   measuredAt: string|null}} DecisionFeed
 */

/** @param {unknown} value */
function text(value) {
  return value === null || value === undefined ? '' : String(value);
}

/** @param {any} raw @returns {CardOption} */
function readOption(raw) {
  return {
    key: text(raw && raw.key),
    label_ro: text(raw && raw.label_ro),
    effect_ro: text(raw && raw.effect_ro),
    recommended: Boolean(raw && raw.recommended),
    apply_type: text(raw && raw.apply_type) || 'none',
    place_ro: raw && raw.place_ro ? String(raw.place_ro) : null,
    steps_ro: raw && raw.steps_ro ? String(raw.steps_ro) : null,
  };
}

/** @param {any} raw @returns {DecisionCard|null} */
function readCard(raw) {
  if (!raw || typeof raw !== 'object' || !raw.card_id || !SOURCE_TYPES.includes(raw.source_type)) return null;
  const options = (Array.isArray(raw.options) ? raw.options : []).filter((/** @type {any} */ x) => x && x.key).map(readOption);
  // the recommended option leads, as the backend orders it; the rest keep their order
  options.sort((a, b) => Number(b.recommended) - Number(a.recommended));
  const version = Number(raw.version);
  return {
    card_id: String(raw.card_id),
    source_type: String(raw.source_type),
    id: text(raw.id),
    kind: text(raw.kind),
    subject: raw.subject && typeof raw.subject === 'object' ? raw.subject : null,
    title_ro: text(raw.title_ro),
    why_ro: text(raw.why_ro),
    effect_ro: text(raw.effect_ro),
    options,
    recommended_option: raw.recommended_option ? String(raw.recommended_option) : null,
    source: text(raw.source),
    status: text(raw.status) || 'PENDING',
    status_ro: text(raw.status_ro),
    chosen_option: raw.chosen_option ? String(raw.chosen_option) : null,
    note: raw.note ? String(raw.note) : null,
    decided_by: raw.decided_by ? String(raw.decided_by) : null,
    decided_at: raw.decided_at ? String(raw.decided_at) : null,
    applied: raw.applied && typeof raw.applied === 'object' ? raw.applied : null,
    apply_error_ro: raw.apply_error_ro ? String(raw.apply_error_ro) : null,
    expires_at: raw.expires_at ? String(raw.expires_at) : null,
    version: Number.isInteger(version) && version >= 1 ? version : null,
    created_at: text(raw.created_at),
    updated_at: text(raw.updated_at),
    waiting: Boolean(raw.waiting),
    answer: raw.answer && typeof raw.answer === 'object' ? raw.answer : {},
    context: raw.context && typeof raw.context === 'object' ? raw.context : null,
    cost_usd: raw.cost_usd === null || raw.cost_usd === undefined || !Number.isFinite(Number(raw.cost_usd)) ? null : Number(raw.cost_usd),
  };
}

/** @param {unknown} list */
function readCards(list) {
  return (Array.isArray(list) ? list : []).map(readCard).filter((card) => card !== null);
}

/** @param {any} raw @returns {DecisionCounts} */
function readCounts(raw) {
  const n = (/** @type {string} */ key) => {
    const value = Number(raw && raw[key]);
    return Number.isInteger(value) && value > 0 ? value : 0;
  };
  return { approvals: n('approvals'), decisions: n('decisions'), waiting_action: n('waiting_action'), letters: n('letters') };
}

/**
 * The feed as the window reads it; a broken answer is an empty window, never a throw.
 * @param {unknown} payload GET /owner/decision-cards
 * @returns {DecisionFeed}
 */
export function readDecisionFeed(payload) {
  const raw = payload && typeof payload === 'object' ? /** @type {any} */ (payload) : {};
  const cards = /** @type {DecisionCard[]} */ (readCards(raw.cards));
  const history = /** @type {DecisionCard[]} */ (readCards(raw.history));
  const count = Number(raw.count);
  return {
    cards,
    history,
    // the feed's count, never fewer than the cards he can see
    count: Math.max(Number.isInteger(count) && count > 0 ? count : 0, cards.length),
    counts: readCounts(raw.counts),
    measuredAt: raw.measured_at ? String(raw.measured_at) : null,
  };
}

/** The top bar key's badge: '' when nothing waits. @param {number} n */
export function decisionsBadge(n) {
  const count = Number(n) || 0;
  if (count <= 0) return '';
  return count > 99 ? '99+' : String(count);
}

/** The key's name for a screen reader, with the count. @param {number} n */
export function decisionsButtonLabel(n) {
  const count = Number(n) || 0;
  // «așteaptă» is the same for one and for many in Romanian
  return count > 0 ? `Decizii — ${countWords(count, 'decizie', 'decizii')} te așteaptă` : 'Decizii — nimic nu te așteaptă';
}

/**
 * A card's route, as the page's api() takes it (without /api/v1), or null when it is not one of
 * the studio's own: a card never sends his answer anywhere else.
 * @param {unknown} path
 */
export function studioPath(path) {
  const value = text(path);
  if (!value.startsWith('/api/v1/') || value.includes('..') || value.includes('//', 1)) return null;
  return value.slice('/api/v1'.length);
}

/** Who asked, in his words. @param {{source_type?: string, source?: string|null}} card */
export function sourceWords(card) {
  const source = text(card.source);
  if (card.source_type === 'approval') return `Cerută de ${source || 'studio'}`;
  if (card.source_type === 'letter') return `Scrisoare de la ${source || 'studio'}`;
  if (source === 'audit') return 'Auditul studioului';
  if (source.startsWith('agent:')) {
    const role = source.slice('agent:'.length);
    return `${ROLE_WORDS[role.toLowerCase()] || role} (propunere)`;
  }
  if (source.startsWith('stage:')) return `Etapa «${source.slice('stage:'.length)}» a zilei`;
  return source || 'Studioul';
}

/** The film a paid-step approval buys for, when it is one; else null. @param {DecisionCard} card */
function sheetOf(card) {
  if (card.source_type !== 'approval' || !card.kind.startsWith('media.')) return null;
  return sheetKeyFor({ action: card.kind, subject: card.subject ? card.subject.id : null, context: card.context });
}

/** What kind of question this is. @param {DecisionCard} card */
function kindWords(card) {
  if (card.source_type === 'approval') return sheetOf(card) ? 'Pas plătit' : 'Cerere de aprobare';
  if (card.source_type === 'letter') return 'Scrisoare';
  return 'Recomandare';
}

/**
 * The Settings tab an option or an applied guided answer sends him to, or null when its place is
 * outside the page (a file, the Google console).
 * @param {{place?: string|null, place_ro?: string|null}|null|undefined} where
 */
export function placeTab(where) {
  if (!where) return null;
  const place = text(where.place);
  if (place && SETTINGS_PLACES[place]) return place;
  const words = text(where.place_ro);
  const found = Object.entries(SETTINGS_PLACES).find(([, label]) => label === words);
  return found ? found[0] : null;
}

/**
 * Whether his accept of this option spends money or changes his policy, and so asks once more.
 * @param {DecisionCard} card @param {CardOption|null|undefined} option
 */
export function needsConfirm(card, option) {
  if (card.source_type === 'approval') return !sheetOf(card);
  if (card.source_type !== 'decision' || !option) return false;
  return ASK_FIRST_TYPES.includes(option.apply_type);
}

/** The confirmation line. @param {DecisionCard} card @param {CardOption|null|undefined} option */
export function confirmWords(card, option) {
  if (card.source_type === 'approval') {
    return `Aprobi «${card.title_ro}»? Cost: ${card.effect_ro || '—'}. Răspunsul acoperă un singur pas.`;
  }
  const label = option ? option.label_ro : card.title_ro;
  const effect = option && option.effect_ro ? `${option.effect_ro} ` : '';
  return `Aplici «${label}»? ${effect}Se aplică acum, prin comanda ta.`;
}

/**
 * The decide route's body (app.decisions DecideCommand): only the fields it takes; the issuer is
 * the key that reached the route, never a field.
 * @param {{decision: 'ACCEPT'|'REFUSE'|'DONE', version: number|null, commandId: string, optionKey?: string|null, note?: string|null}} o
 */
export function decideCommand(o) {
  /** @type {Record<string, unknown>} */
  const command = { command_id: o.commandId, expected_version: o.version, decision: o.decision };
  if (o.decision === 'ACCEPT' && o.optionKey) command.option_key = o.optionKey;
  const note = text(o.note).trim().slice(0, 500);
  if (note) command.note = note;
  return command;
}

/** @param {DecisionCard} card @param {string|null} key */
function optionNamed(card, key) {
  return card.options.find((option) => option.key === key) || null;
}

/** «Nota ta: «…»» when he wrote one. @param {string|null} note */
function noteTail(note) {
  return note ? ` Nota ta: «${note}»` : '';
}

/**
 * What his answer did, for the history.
 * @param {Pick<DecisionCard, 'source_type'|'status'|'options'> & Partial<DecisionCard>} card
 */
export function appliedWords(card) {
  const note = card.note || null;
  if (card.source_type === 'approval') {
    if (card.status === 'APPROVED') return `Ai aprobat; studioul a putut face pasul.${noteTail(note)}`;
    if (card.status === 'REFUSED') return `Ai refuzat cererea; refuzul rămâne în registru.${noteTail(note)}`;
    if (card.status === 'EXPIRED') return 'Cererea a expirat fără răspunsul tău.';
    return card.status_ro || '';
  }
  const applied = card.applied || {};
  if (card.status === 'REFUSED') return `Ai refuzat. Nimic nu s-a schimbat.${noteTail(note)}`;
  if (card.status === 'WITHDRAWN') return `Retras: ${applied.withdrawn_reason_ro || 'întrebarea nu mai stă.'}`;
  if (card.status === 'EXPIRED') return 'A expirat fără răspunsul tău.';
  const option = optionNamed(/** @type {DecisionCard} */ (card), card.chosen_option || null);
  const label = option ? option.label_ro : '';
  if (card.status === 'WAITING_FOR_OWNER_ACTION') {
    return `Așteaptă acțiunea ta: ${applied.place_ro || (option && option.place_ro) || ''}`.trim();
  }
  if (applied.completed_by === 'owner') {
    // since 2026-10-04 his DONE closes a card only when the studio reads it done, or when only he can confirm it
    if (applied.done_reading === 'MET') return 'Ai marcat-o făcută, iar studioul a văzut pasul făcut.';
    if (applied.done_reading === 'ONLY_OWNER') return 'Ai marcat-o făcută; doar tu o poți confirma.';
    return 'Ai marcat-o făcută.';
  }
  if (applied.completed_by === 'condition') return 'S-a rezolvat: studioul a văzut că nu mai trebuie nimic.';
  const type = text(applied.type);
  const command = COMMAND_WORDS[text(applied.command)] || TYPE_WORDS[type];
  if (command) return `Aplicat prin comanda ta (${command}): «${label}».${noteTail(note)}`;
  if (type === 'record') return `Ai ales «${label}»; răspunsul tău a fost înregistrat.${applied.follow_up_ro ? ` ${applied.follow_up_ro}` : ''}${noteTail(note)}`;
  if (type === 'none') return `Ai ales «${label}»: ${applied.result_ro || 'nimic nu se schimbă.'}${noteTail(note)}`;
  return `${card.status_ro || 'Acceptat'}${label ? `: «${label}»` : ''}.${noteTail(note)}`;
}

/**
 * @typedef {{status: 'DONE'|'WAITING'|'STALE'|'FAILED'|'GONE'|'REFUSED'|'INVALID'|'SHEET', reload: boolean,
 *   message: string, place: string|null, sheet?: string}} AnswerResult
 */

/** @param {any} error @returns {AnswerResult} */
function failure(error) {
  const message = error instanceof Error ? error.message : 'Răspunsul nu a putut fi trimis.';
  const status = error && error.status;
  if (status === 409) return { status: 'STALE', reload: true, message, place: null };
  if (status === 404) return { status: 'GONE', reload: true, message, place: null };
  if (status === 403) return { status: 'REFUSED', reload: false, message, place: null };
  // a 422 (his accept could not be applied), a 5xx or no answer at all: the window reads again
  return { status: 'FAILED', reload: true, message, place: null };
}

/** @type {AnswerResult} */
const NO_ROUTE = { status: 'INVALID', reload: false, message: 'Cardul nu numește o rută a studioului; nu s-a trimis nimic.', place: null };

/**
 * Sends his answer to the route the card names, and says what happened.
 * @param {(path: string, options?: any) => Promise<any>} api the page's api() (prefixes /api/v1)
 * @param {DecisionCard} card
 * @param {{decision: 'ACCEPT'|'REFUSE'|'DONE'|'REPLY'|'RESOLVE', commandId: string, optionKey?: string|null, note?: string|null}} answer
 * @returns {Promise<AnswerResult>}
 */
export async function answerCard(api, card, answer) {
  const note = text(answer.note).trim();
  if (card.source_type === 'decision') {
    if (!['ACCEPT', 'REFUSE', 'DONE'].includes(answer.decision)) return { ...NO_ROUTE, message: 'Răspuns necunoscut.' };
    const path = studioPath(card.answer && card.answer.path);
    if (!path) return NO_ROUTE;
    const body = decideCommand({ decision: /** @type {'ACCEPT'|'REFUSE'|'DONE'} */ (answer.decision), version: card.version, commandId: answer.commandId, optionKey: answer.optionKey, note });
    try {
      const result = await api(path, { method: 'POST', body: JSON.stringify(body) });
      const view = readCard({ ...(result && result.decision), card_id: card.card_id, source_type: 'decision' }) || card;
      if (view.status === 'WAITING_FOR_OWNER_ACTION') {
        const applied = view.applied || {};
        const option = optionNamed(view, view.chosen_option);
        const where = applied.place_ro || (option && option.place_ro) || '';
        const steps = applied.steps_ro || (option && option.steps_ro) || '';
        if (answer.decision === 'DONE') {
          // the studio did not see the step done: it says what is missing, and he stays on the card
          const missing = view.apply_error_ro || 'Studioul nu vede încă pasul făcut, așa că cardul rămâne deschis.';
          return { status: 'WAITING', reload: true, message: `${missing}${where ? ` Unde: ${where}.` : ''}`, place: null };
        }
        return {
          status: 'WAITING',
          reload: true,
          message: `Cardul așteaptă acțiunea ta${where ? `: ${where}` : ''}.${steps ? ` ${steps}` : ''}`,
          place: placeTab(applied) || placeTab(option),
        };
      }
      return { status: 'DONE', reload: true, message: appliedWords(view), place: null };
    } catch (error) {
      return failure(error);
    }
  }
  if (card.source_type === 'approval') {
    const sheet = sheetOf(card);
    if (answer.decision === 'ACCEPT' && sheet) {
      return { status: 'SHEET', reload: false, message: 'Un pas plătit se aprobă pe foaia de filmare, unde sunt scenele, modelele și plafonul.', place: null, sheet };
    }
    if (answer.decision !== 'ACCEPT' && answer.decision !== 'REFUSE') return { ...NO_ROUTE, message: 'Răspuns necunoscut.' };
    const path = studioPath(card.answer && card.answer.path);
    if (!path) return NO_ROUTE;
    const decision = answer.decision === 'ACCEPT' ? 'APPROVED' : 'REFUSED';
    try {
      await api(path, { method: 'POST', body: JSON.stringify(approvalDecisionCommand(card.id, decision, answer.commandId, note.slice(0, 500) || undefined)) });
      return {
        status: 'DONE',
        reload: true,
        message: decision === 'APPROVED' ? 'Cererea a fost aprobată; studioul poate relua acțiunea permisă.' : 'Cererea a fost refuzată; refuzul rămâne în registru.',
        place: null,
      };
    } catch (error) {
      return failure(error);
    }
  }
  if (card.source_type === 'letter') {
    if (answer.decision === 'REPLY') {
      if (!note) return { status: 'INVALID', reload: false, message: 'Scrie întâi răspunsul tău.', place: null };
      const path = studioPath(card.answer && card.answer.reply_path);
      if (!path) return NO_ROUTE;
      try {
        await api(path, { method: 'POST', body: JSON.stringify({ text: note.slice(0, 4000) }) });
        return { status: 'DONE', reload: true, message: 'Răspunsul tău a plecat; angajatul îl citește la următoarea trecere a lucrătorului.', place: null };
      } catch (error) {
        return failure(error);
      }
    }
    if (answer.decision === 'RESOLVE') {
      const path = studioPath(card.answer && card.answer.resolve_path);
      if (!path) return NO_ROUTE;
      try {
        await api(path, { method: 'POST', body: JSON.stringify(resolveCommand(note)) });
        return { status: 'DONE', reload: true, message: 'Scrisoarea s-a închis.', place: null };
      } catch (error) {
        return failure(error);
      }
    }
  }
  return { ...NO_ROUTE, message: 'Răspuns necunoscut.' };
}

/** Whether an event of the socket may have changed what the window shows. @param {any} event */
export function refreshesOn(event) {
  if (!event || typeof event !== 'object') return false;
  const type = text(event.event_type || event.type);
  return type.startsWith('owner.') || type.startsWith('governance.approval_') || type.startsWith('agent.message_') || type.startsWith('economy.budget_');
}

// --------------------------------------------------------------------------------- drawing

/**
 * @typedef {{escape: (value: unknown) => string, timezone?: string, busy?: boolean, confirming?: boolean,
 *   draft?: {option?: string|null, note?: string}, thread?: string|null}} CardOptions
 */

/** @param {CardOptions} o @param {DecisionCard} card */
function chosenKey(o, card) {
  const wanted = o.draft && o.draft.option;
  if (wanted && optionNamed(card, wanted)) return wanted;
  return card.recommended_option && optionNamed(card, card.recommended_option) ? card.recommended_option : (card.options[0] ? card.options[0].key : null);
}

/** @param {string} label @param {string} action @param {DecisionCard} card @param {CardOptions} o @param {string} [kind] @param {string} [extra] */
function key(label, action, card, o, kind = 'quiet', extra = '') {
  const e = o.escape;
  return `<button type="button" class="${kind} decision-key" data-decision-action="${action}" data-card="${e(card.card_id)}"${extra}${o.busy ? ' disabled' : ''}>${e(label)}</button>`;
}

/** @param {DecisionCard} card @param {CardOptions} o @param {string} label */
function noteBox(card, o, label) {
  const e = o.escape;
  const value = o.draft && o.draft.note ? o.draft.note : '';
  const limit = card.source_type === 'letter' ? 4000 : 500;
  return `<label class="decision-note">${e(label)}<textarea data-decision-note data-card="${e(card.card_id)}" maxlength="${limit}" rows="2"${o.busy ? ' disabled' : ''}>${e(value)}</textarea></label>`;
}

/** The options of a decision card: a choice when there are several. @param {DecisionCard} card @param {CardOptions} o */
function optionsHtml(card, o) {
  const e = o.escape;
  const chosen = chosenKey(o, card);
  const several = card.options.length > 1;
  const locked = o.busy || o.confirming;
  const rows = card.options.map((option) => {
    const tab = option.apply_type === 'guided' ? placeTab(option) : null;
    const where = option.apply_type === 'guided' && option.place_ro
      ? `<span class="decision-option-place">${tab ? `Accept deschide locul: ${e(option.place_ro)}; cardul așteaptă până termini.` : `Unde: ${e(option.place_ro)}`}</span>`
      : '';
    const body = `<span class="decision-option-text"><span class="decision-option-label">${e(option.label_ro)}${option.recommended ? ' <span class="decision-recommended">Recomandat</span>' : ''}</span>`
      + `${option.effect_ro ? `<span class="decision-option-effect">${e(option.effect_ro)}</span>` : ''}${where}</span>`;
    const lit = `data-recommended="${option.recommended ? 'true' : 'false'}"`;
    if (!several) return `<div class="decision-option" ${lit}>${body}</div>`;
    return `<label class="decision-option" ${lit}><input type="radio" name="decision-option-${e(card.id)}" value="${e(option.key)}" data-decision-option data-card="${e(card.card_id)}"${option.key === chosen ? ' checked' : ''}${locked ? ' disabled' : ''} />${body}</label>`;
  }).join('');
  return several
    ? `<fieldset class="decision-options"><legend class="decision-sub">Ce alegi</legend>${rows}</fieldset>`
    : `<div class="decision-options">${rows}</div>`;
}

/** @param {DecisionCard} card @param {CardOptions} o */
function confirmHtml(card, o) {
  const option = optionNamed(card, chosenKey(o, card));
  return `<div class="decision-ask" role="group" aria-label="Confirmă decizia">`
    + `<p class="decision-ask-q">${o.escape(confirmWords(card, option))}</p>`
    + `<div class="decision-keys">${key('Da, aplică', 'confirm', card, o, 'secondary')}${key('Nu acum', 'cancel', card, o)}</div></div>`;
}

/** The keys and the note of a card that waits. @param {DecisionCard} card @param {CardOptions} o */
function answerHtml(card, o) {
  const e = o.escape;
  if (card.source_type === 'letter') {
    const thread = o.thread ? key('Deschide firul', 'thread', card, o, 'quiet', ` data-decision-thread="${e(o.thread)}"`) : '';
    return noteBox(card, o, 'Răspunsul tău')
      + `<div class="decision-keys">${key('Trimite răspunsul', 'reply', card, o, 'secondary')}${key('Închid scrisoarea', 'resolve', card, o)}${thread}</div>`;
  }
  if (card.source_type === 'approval') {
    const sheet = sheetOf(card);
    if (o.confirming && !sheet) return confirmHtml(card, o);
    const accept = sheet
      ? `<button type="button" class="secondary decision-key" data-sheet-open="${e(sheet)}"${o.busy ? ' disabled' : ''}>Accept pe foaia de filmare</button>`
      : key('Accept', 'accept', card, o, 'secondary');
    return noteBox(card, o, 'Nota ta (opțional)') + `<div class="decision-keys">${accept}${key('Refuz', 'refuse', card, o)}</div>`;
  }
  if (card.status === 'WAITING_FOR_OWNER_ACTION') {
    const applied = card.applied || {};
    const option = optionNamed(card, card.chosen_option);
    const where = applied.place_ro || (option && option.place_ro) || '';
    const steps = applied.steps_ro || (option && option.steps_ro) || '';
    const tab = placeTab(applied) || placeTab(option);
    return `<div class="decision-guided">${where ? `<p class="decision-place"><span class="decision-sub">Unde</span> ${e(where)}</p>` : ''}${steps ? `<p class="decision-steps">${e(steps)}</p>` : ''}</div>`
      + noteBox(card, o, 'Nota ta (opțional)')
      + `<div class="decision-keys">${tab ? key('Deschide locul', 'place', card, o, 'secondary', ` data-decision-place="${e(tab)}"`) : ''}`
      + `${key('Am făcut-o', 'done', card, o, tab ? 'quiet' : 'secondary')}${key('Refuz', 'refuse', card, o)}</div>`;
  }
  if (o.confirming) return optionsHtml(card, o) + confirmHtml(card, o);
  return optionsHtml(card, o) + noteBox(card, o, 'Nota ta (opțional)')
    + `<div class="decision-keys">${key('Accept', 'accept', card, o, 'secondary')}${key('Refuz', 'refuse', card, o)}</div>`;
}

/** A paid step's film and step. @param {DecisionCard} card @param {CardOptions} o */
function filmLine(card, o) {
  const sheet = sheetOf(card);
  if (!sheet) return '';
  const context = card.context || {};
  const step = context.step ? STEP_WORDS[String(context.step)] || String(context.step) : '';
  return `<p class="decision-film">${step ? `Pasul: ${o.escape(step)}` : 'Un pas plătit'}${context.plan_hash ? ` · foaia ${o.escape(context.plan_hash)}` : ''}. `
    + 'Răspunsul «da» se dă pe foaia de filmare, unde sunt scenele, modelele și plafonul.</p>';
}

/**
 * One card: what, why, who asked and when; the options and their effect; his keys.
 * @param {DecisionCard} card
 * @param {CardOptions} o
 */
export function cardHtml(card, o) {
  const e = o.escape;
  const at = card.created_at ? `<time datetime="${e(card.created_at)}">${e(when(card.created_at, o.timezone))}</time>` : '';
  const waiting = card.status === 'WAITING_FOR_OWNER_ACTION';
  const cost = card.source_type === 'approval' && card.effect_ro
    ? `<p class="decision-cost"><span class="decision-sub">Cost</span> ${e(card.effect_ro)}</p>`
    : card.effect_ro && card.source_type === 'decision' ? `<p class="decision-effect"><span class="decision-sub">Efect</span> ${e(card.effect_ro)}</p>` : '';
  const approvalOptions = card.source_type === 'approval'
    ? `<ul class="decision-outcomes">${card.options.map((option) => `<li><strong>${e(option.label_ro)}</strong> — ${e(option.effect_ro)}</li>`).join('')}</ul>`
    : '';
  const error = card.apply_error_ro ? `<p class="decision-error" role="alert">${e(card.apply_error_ro)}</p>` : '';
  const reopenedWhy = waiting && card.source_type === 'decision' && card.applied && card.applied.reopened_reason_ro
    ? `<p class="decision-reopened">${e(card.applied.reopened_reason_ro)}</p>`
    : '';
  return `<article class="decision-card" data-card="${e(card.card_id)}" data-source-type="${e(card.source_type)}" data-status="${e(card.status)}" aria-labelledby="dc-${e(card.id)}">`
    + '<header class="dcard-head">'
    + `<span class="decision-kind">${e(kindWords(card))}</span>`
    + `<span class="decision-from">${e(sourceWords(card))}${at ? ' · ' : ''}${at}</span>`
    + (waiting ? `<span class="dcard-state">${e(card.status_ro || 'în așteptarea acțiunii tale')}</span>` : '')
    + '</header>'
    + `<h3 class="dcard-title" id="dc-${e(card.id)}">${e(card.title_ro || '(fără titlu)')}</h3>`
    + (card.why_ro ? `<p class="decision-why">${e(card.why_ro)}</p>` : '')
    + filmLine(card, o)
    + cost
    + approvalOptions
    + reopenedWhy
    + error
    + answerHtml(card, o)
    + '</article>';
}

/** A closed card in the history: what he answered, when, and what it applied. @param {DecisionCard} card @param {CardOptions} o */
function historyHtml(card, o) {
  const e = o.escape;
  const stamp = card.decided_at || card.updated_at;
  const at = stamp ? `<time datetime="${e(stamp)}">${e(when(stamp, o.timezone))}</time>` : '';
  return `<article class="decision-card is-closed" data-card="${e(card.card_id)}" data-source-type="${e(card.source_type)}" data-status="${e(card.status)}">`
    + '<header class="dcard-head">'
    + `<span class="decision-kind">${e(kindWords(card))}</span>`
    + `<span class="decision-from">${e(sourceWords(card))}${at ? ' · ' : ''}${at}</span>`
    + `<span class="dcard-state" data-status="${e(card.status)}">${e(card.status_ro || card.status)}</span>`
    + '</header>'
    + `<h3 class="dcard-title">${e(card.title_ro || '(fără titlu)')}</h3>`
    + `<p class="decision-applied">${e(appliedWords(card))}</p>`
    + '</article>';
}

/**
 * The window's body: the two tabs and the open tab's cards.
 * @param {DecisionFeed} feed
 * @param {{escape: (value: unknown) => string, timezone?: string, tab: 'waiting'|'history',
 *   read: 'pending'|'ok'|'failed'|'missing', error?: string, busy?: string|null, confirming?: string|null,
 *   drafts?: Map<string, {option?: string|null, note?: string}>, threads?: Map<string, string>}} o
 */
export function windowHtml(feed, o) {
  const e = o.escape;
  const tab = (/** @type {'waiting'|'history'} */ name, /** @type {string} */ label, /** @type {number} */ n) => {
    const on = o.tab === name;
    return `<button type="button" role="tab" id="decisions-tab-${name}" aria-selected="${on}" aria-controls="decisions-panel" data-decisions-tab="${name}" tabindex="${on ? 0 : -1}" class="decisions-tab">${label} <span class="decisions-tab-count">${n}</span></button>`;
  };
  const tabs = `<div class="decisions-tabs" role="tablist" aria-label="Deciziile tale">${tab('waiting', 'Te așteaptă', feed.cards.length)}${tab('history', 'Istoric', feed.history.length)}</div>`;
  let inner;
  if (o.read === 'missing') {
    inner = '<p class="decisions-empty">Backend-ul pornit acum nu are încă fereastra deciziilor; o primește după ce repornești studioul.</p>';
  } else if (o.read === 'failed' && !feed.cards.length && !feed.history.length) {
    inner = `<p class="decisions-empty decision-error">Deciziile nu au putut fi citite: ${e(o.error || 'fără răspuns')}</p>`;
  } else if (o.tab === 'history') {
    inner = feed.history.length
      ? feed.history.map((card) => historyHtml(card, { escape: e, timezone: o.timezone })).join('')
      : `<p class="decisions-empty">${o.read === 'pending' ? 'Se citesc deciziile…' : 'Nu ai răspuns încă la niciun card.'}</p>`;
  } else {
    inner = feed.cards.length
      ? feed.cards.map((card) => cardHtml(card, {
        escape: e,
        timezone: o.timezone,
        busy: o.busy === card.card_id,
        confirming: o.confirming === card.card_id,
        draft: o.drafts ? o.drafts.get(card.card_id) : undefined,
        thread: o.threads ? o.threads.get(card.id) || null : null,
      })).join('')
      : `<p class="decisions-empty">${o.read === 'pending' ? 'Se citesc deciziile…' : 'Nimic nu așteaptă decizia ta.'}</p>`;
  }
  return `${tabs}<div class="decisions-panel" role="tabpanel" id="decisions-panel" aria-labelledby="decisions-tab-${o.tab}" tabindex="0">${inner}</div>`;
}
