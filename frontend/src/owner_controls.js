import { channelTypeWord, providerName } from './dialog_words.js';

/**
 * W34 — THE OWNER'S OWN DECISIONS, ON THE PAGE.
 *
 * The preflight told the Owner that two of his decisions could be made «deocamdată doar prin
 * API-ul studioului»: whether the Director may approve the serial's episodes, and what a token of
 * each model his employees think with costs. Both are his alone. The page now has a control for
 * each, and neither is ever set by the page on its own: the switch asks first and sends the
 * backend's versioned command, the price is what he types. Every answer is shown as the backend
 * gave it; a refusal is the backend's own sentence.
 *
 * - The Director's right: `POST /publishing/channels/{id}/publish-policy` with
 *   `director_may_approve_episodes` and `expected_version` (the channel's `policy_version`), on the
 *   OFFICE_SERIAL channel only (`backend/app/publishing/schemas.py` PublishPolicyCommand).
 * - A token price: `PUT /economy/prices`, one command per side (`per_1m_input_tokens`,
 *   `per_1m_output_tokens`), USD as a decimal string, with `expected_version` when a price is
 *   replaced (`backend/app/economy/prices.py` PriceCommand).
 */

/** The channel type the Director's right belongs to. */
export const SERIAL_CHANNEL_TYPE = 'OFFICE_SERIAL';

/** The switch's name (glossary W34). */
export const DIRECTOR_RIGHT_LABEL = 'Directoarea poate aproba episoadele serialului';

/** What the switch does, and what it spends (glossary W34): said under the switch, always. */
export const DIRECTOR_RIGHT_MEANING =
  'Pornit: un episod pe care Directoarea îl citește și îl trece este aprobat fără clicul tău, iar rularea zilei îi face storyboardul și îl randează, cu bani din bugetul zilei. Oprit: fiecare episod rămâne ciornă până îl aprobi tu, și nimic nu se randează pentru el până atunci.';

/**
 * The serial's channel, or null when the studio has none.
 * @param {any[]|null|undefined} channels /publishing/channels
 */
export function serialChannel(channels) {
  return (Array.isArray(channels) ? channels : []).find((c) => c && c.channel_type === SERIAL_CHANNEL_TYPE) || null;
}

/**
 * A channel's facts in the page's words: its type, its YouTube account's title (the raw id only in
 * the tooltip) and its policy's version.
 * @param {any} channel
 * @returns {{type: string, account: string, accountTitle: string, version: number}}
 */
export function channelFacts(channel) {
  const c = channel || {};
  const title = String(c.youtube_channel_title || c.youtube_connection_name || '').trim();
  return {
    type: channelTypeWord(String(c.channel_type || '')),
    account: title || (c.remote_channel_id ? 'nelegat' : 'nesetat'),
    accountTitle: c.remote_channel_id ? `ID extern: ${c.remote_channel_id}` : '',
    version: Number(c.policy_version) >= 1 ? Number(c.policy_version) : 1,
  };
}

/**
 * The versioned command that sets the Director's right, and nothing else (a field left out keeps
 * its value on the backend).
 * @param {any} channel @param {boolean} on @param {string} commandId
 */
export function directorRightCommand(channel, on, commandId) {
  return { command_id: commandId, expected_version: channelFacts(channel).version, director_may_approve_episodes: Boolean(on) };
}

/**
 * W36: the switch's sentence set as its two states, word for word (split at «Oprit:»), the line of
 * the state it is in now marked, so the plate says what ON does and what OFF does beside the switch.
 * @param {boolean} on the state now
 * @returns {{state: 'on'|'off', text: string, now: boolean}[]}
 */
export function directorRightLines(on) {
  const at = DIRECTOR_RIGHT_MEANING.indexOf(' Oprit: ');
  return [
    { state: 'on', text: DIRECTOR_RIGHT_MEANING.slice(0, at), now: Boolean(on) },
    { state: 'off', text: DIRECTOR_RIGHT_MEANING.slice(at + 1), now: !on },
  ];
}

/** The confirmation's question. @param {boolean} on the state asked for */
export function directorRightQuestion(on) {
  return on
    ? 'Îi dai Directoarei dreptul să aprobe episoadele serialului?'
    : 'Îi iei Directoarei dreptul să aprobe episoadele serialului?';
}

/** The confirmation's key. @param {boolean} on */
export function directorRightConfirmKey(on) {
  return on ? 'Da, dă-i dreptul' : 'Da, ia-i dreptul';
}

/**
 * The backend's answer in words; '' when the answer is not one the page can read (it is never
 * dressed as a success).
 * @param {any} result PublishPolicyResult
 */
export function directorRightAnswer(result) {
  const channel = result && result.channel;
  if (!channel || (result.status !== 'COMMITTED' && result.status !== 'NO_CHANGE')) return '';
  const version = channelFacts(channel).version;
  if (result.status === 'NO_CHANGE') return `Nimic de schimbat: politica era deja așa (versiunea ${version}).`;
  return channel.director_may_approve_episodes
    ? `Salvat: Directoarea poate aproba episoadele serialului. Politica canalului este acum la versiunea ${version}.`
    : `Salvat: Directoarea nu mai poate aproba episoadele serialului. Politica canalului este acum la versiunea ${version}.`;
}

/* ------------------------------------------------------------------------ the token prices */

/** The two units an employee's run is costed in (backend preflight.TOKEN_UNITS). */
export const TOKEN_UNITS = /** @type {const} */ (['per_1m_input_tokens', 'per_1m_output_tokens']);

/** The section's sentence (glossary W34). */
export const PRICES_MEANING =
  'Fiecare rulare a unui angajat se costă cu prețul pe care îl scrii aici, pe un milion de tokenuri citite (intrare) și scrise (ieșire). Un model fără preț pe ambele părți lasă rularea fără cost în cărți. Prețul nu cheltuie nimic și nimeni nu îl ghicește în locul tău.';

const PRICE_ERROR = 'Scrie prețul ca număr, de exemplu 0,50 (cel mult 6 zecimale).';
/** When one side is written and the other is not. */
export const PRICE_BOTH = 'Scrie ambele prețuri: un preț doar pe o parte nu este un preț.';

/**
 * A price as the Owner writes it («0,50» or «0.50»), as the backend's decimal string; refused when
 * it is not one (the backend's own pattern: up to 9 digits, up to 6 decimals, never negative).
 * @param {unknown} text
 * @returns {{ok: true, usd: string} | {ok: false, error: string}}
 */
export function priceInput(text) {
  const raw = String(text ?? '').trim().replace(/\s+/g, '');
  const usd = raw.replace(',', '.');
  if (!/^\d{1,9}(\.\d{1,6})?$/.test(usd)) return { ok: false, error: PRICE_ERROR };
  return { ok: true, usd };
}

/**
 * The models the preflight found without a price on both token sides. Read as data: the backend's
 * `value.unpriced` when it sends one, else its detail when that is exactly a list of
 * «kind:model» (never a sentence).
 * @param {any} check the preflight's model_prices line
 * @returns {{kind: string, model: string}[]}
 */
export function unpricedModels(check) {
  if (!check || check.ok) return [];
  const listed = check.value && Array.isArray(check.value.unpriced) ? check.value.unpriced : null;
  if (listed) {
    return listed
      .map((/** @type {any} */ u) => ({ kind: String(u.provider_kind || u.kind || '').toLowerCase(), model: String(u.model || u.resource || '') }))
      .filter((u) => u.kind && u.model);
  }
  const items = String(check.detail || '').split(',').map((s) => s.trim()).filter(Boolean);
  if (!items.length || !items.every((s) => /^[a-z][a-z0-9_-]*:\S+$/.test(s))) return [];
  return items.map((s) => {
    const at = s.indexOf(':');
    return { kind: s.slice(0, at), model: s.slice(at + 1) };
  });
}

/**
 * @typedef {{usd: string, usd_micros: number, version: number}} SidePrice
 * @typedef {{kind: string, model: string, input: SidePrice|null, output: SidePrice|null, priced: boolean, wide?: boolean}} PriceRow
 */

/**
 * W36: the resource that prices every model of a provider that has no price of its own
 * (backend economy/prices.py ANY_RESOURCE; PriceCommand takes it as `resource`).
 */
export const ANY_MODEL = '*';

/** The tones a provider's mark is drawn in: the page's cool inks, never a state's warning or alarm. */
const MARK_TONES = /** @type {const} */ (['info', 'forest', 'teal']);

/**
 * W36: a provider's mark, from its name alone (no logo): its first letter, set on the page's hexagon
 * (style.css .provider-mark), in one tone the name always gets.
 * @param {unknown} kind the price table's key («ollama»)
 * @returns {{letter: string, name: string, tone: typeof MARK_TONES[number]}}
 */
export function providerMark(kind) {
  const key = String(kind ?? '').trim().toLowerCase();
  const name = providerName(key);
  const letter = (name.match(/[\p{L}\p{N}]/u) || ['—'])[0].toUpperCase();
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return { letter, name, tone: MARK_TONES[h % MARK_TONES.length] };
}

/** The price table's key: lower case, as the backend's PriceCommand pattern takes it. */
const KIND = /^[a-z][a-z0-9_-]*$/;

/**
 * W36: the models the studio knows (GET /settings: each model with its connection, which is an
 * integration or an older provider record), by the kind the price table is keyed by (lower case;
 * backend preflight _price_check). Unique, by provider then model.
 * @param {any} settings /settings
 * @returns {{kind: string, model: string, available: boolean}[]}
 */
export function knownModels(settings) {
  if (!settings || typeof settings !== 'object') return [];
  /** @type {Map<string, string>} */
  const kinds = new Map();
  for (const i of Array.isArray(settings.integrations) ? settings.integrations : []) if (i && i.id) kinds.set(String(i.id), String(i.kind || '').toLowerCase());
  for (const p of Array.isArray(settings.legacy_providers) ? settings.legacy_providers : []) if (p && p.id && !kinds.has(String(p.id))) kinds.set(String(p.id), String(p.provider_type || '').toLowerCase());
  /** @type {Map<string, {kind: string, model: string, available: boolean}>} */
  const out = new Map();
  for (const m of Array.isArray(settings.models) ? settings.models : []) {
    const kind = kinds.get(String(m && m.provider_id)) || '';
    const model = String((m && m.model_name) || '').trim();
    if (!KIND.test(kind) || !model) continue;
    const key = `${kind}\u0000${model}`;
    const was = out.get(key);
    out.set(key, { kind, model, available: Boolean(m.is_available) || Boolean(was && was.available) });
  }
  const by = (/** @type {string} */ a, /** @type {string} */ b) => a.localeCompare(b, 'en', { numeric: true });
  return [...out.values()].sort((a, b) => by(a.kind, b.kind) || by(a.model, b.model));
}

/**
 * W36: whether a model the Owner names can join the price list: one the studio knows at that
 * provider, not already listed. Nothing is sent; the price is saved by the row's own key.
 * @param {string} kind @param {unknown} name
 * @param {{kind: string, model: string}[]} known knownModels
 * @param {{kind: string, model: string}[]} rows the rows listed now
 * @returns {{ok: true, row: {kind: string, model: string}} | {ok: false, error: string}}
 */
export function checkNewModel(kind, name, known, rows) {
  const model = String(name ?? '').trim();
  const provider = providerName(kind);
  if (!model) return { ok: false, error: 'Scrie numele modelului, așa cum îl știe studioul.' };
  if (model.includes(ANY_MODEL)) return { ok: false, error: `Pentru toate modelele unui furnizor folosește rândul „Toate modelele ${provider}”.` };
  if (!known.some((k) => k.kind === kind && k.model === model)) {
    return { ok: false, error: `Studioul nu cunoaște modelul „${model}” la ${provider}. Alege unul din lista lui.` };
  }
  if (rows.some((r) => r.kind === kind && r.model === model)) return { ok: false, error: 'Modelul este deja în listă.' };
  return { ok: true, row: { kind, model } };
}

/**
 * One side of a price, from the books' row.
 * @param {any} p
 * @returns {SidePrice}
 */
function sideOf(p) {
  return { usd: String(p.usd ?? ''), usd_micros: Number(p.usd_micros), version: Number(p.version) || 1 };
}

/**
 * W36: one provider-wide row per provider (the backend's «*»): the kinds given (the providers the
 * studio's models run on) and every kind the books already price that way.
 * @param {any[]|null|undefined} prices /economy/prices .prices (active)
 * @param {string[]} kinds
 * @returns {PriceRow[]}
 */
export function providerWideRows(prices, kinds) {
  /** @type {Map<string, PriceRow>} */
  const rows = new Map();
  const row = (/** @type {string} */ kind) => {
    if (!rows.has(kind)) rows.set(kind, { kind, model: ANY_MODEL, input: null, output: null, priced: false, wide: true });
    return /** @type {PriceRow} */ (rows.get(kind));
  };
  for (const k of kinds) if (KIND.test(String(k))) row(String(k));
  for (const p of Array.isArray(prices) ? prices : []) {
    if (!p || p.active === false || !TOKEN_UNITS.includes(p.unit) || String(p.resource) !== ANY_MODEL) continue;
    const r = row(String(p.provider_kind || ''));
    if (p.unit === 'per_1m_input_tokens') r.input = sideOf(p);
    else r.output = sideOf(p);
  }
  for (const r of rows.values()) r.priced = Boolean(r.input && r.output);
  return [...rows.values()].sort((a, b) => a.kind.localeCompare(b.kind, 'en'));
}

/**
 * One row per model: the ones the preflight found unpriced, then every model the books price per
 * token, each with what each side costs now and its version.
 * @param {any} preflight /runbook/preflight
 * @param {any[]|null|undefined} prices /economy/prices .prices (active)
 * @param {{kind: string, model: string}[]} [added] W36: models the Owner put in the list (checkNewModel)
 * @returns {PriceRow[]}
 */
export function tokenPriceRows(preflight, prices, added = []) {
  const checks = preflight && Array.isArray(preflight.checks) ? preflight.checks : [];
  const line = checks.find((c) => c && c.name === 'model_prices');
  /** @type {Map<string, PriceRow>} */
  const rows = new Map();
  const row = (/** @type {string} */ kind, /** @type {string} */ model) => {
    const key = `${kind}\u0000${model}`;
    if (!rows.has(key)) rows.set(key, { kind, model, input: null, output: null, priced: false });
    return /** @type {PriceRow} */ (rows.get(key));
  };
  for (const u of unpricedModels(line)) row(u.kind, u.model);
  // W36: a model the Owner added from the studio's own list (checkNewModel), until it is priced
  for (const a of Array.isArray(added) ? added : []) if (a && a.kind && a.model) row(String(a.kind), String(a.model));
  for (const p of Array.isArray(prices) ? prices : []) {
    // W36: the provider-wide price («*») is its own row (providerWideRows), not a model's
    if (!p || p.active === false || !TOKEN_UNITS.includes(p.unit) || String(p.resource) === ANY_MODEL) continue;
    const r = row(String(p.provider_kind || ''), String(p.resource || ''));
    if (p.unit === 'per_1m_input_tokens') r.input = sideOf(p);
    else r.output = sideOf(p);
  }
  for (const r of rows.values()) r.priced = Boolean(r.input && r.output);
  // W35: one fixed order, by provider then model. The preflight is recomputed after every save, so
  // «unpriced first» moved the row the Owner had just priced to the bottom and put another model
  // under his hand (found driving the real backend: the next row's save priced the wrong model).
  const by = (/** @type {string} */ a, /** @type {string} */ b) => a.localeCompare(b, 'en', { numeric: true });
  return [...rows.values()].sort((a, b) => by(a.kind, b.kind) || by(a.model, b.model));
}

/**
 * The two commands that price a model, input then output.
 * @param {PriceRow} row @param {string} inputUsd @param {string} outputUsd @param {[string, string]} ids command ids
 */
export function priceCommands(row, inputUsd, outputUsd, ids) {
  const one = (/** @type {string} */ unit, /** @type {string} */ usd, /** @type {SidePrice|null} */ now, /** @type {string} */ id) => ({
    command_id: id,
    provider_kind: row.kind,
    resource: row.model,
    unit,
    usd,
    provenance: 'OWNER',
    ...(now ? { expected_version: now.version } : {}),
  });
  return [one(TOKEN_UNITS[0], inputUsd, row.input, ids[0]), one(TOKEN_UNITS[1], outputUsd, row.output, ids[1])];
}

/** USD micros as the page writes money: a decimal comma, two decimals at least. @param {number} micros */
export function usdWords(micros) {
  const n = Number(micros) / 1e6;
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('ro-RO', { minimumFractionDigits: 2, maximumFractionDigits: 6, useGrouping: false });
}

/**
 * The answer, from the backend's two views.
 * @param {PriceRow} row @param {any} input @param {any} output
 */
export function priceAnswer(row, input, output) {
  return `Salvat: ${row.kind} · ${row.model === ANY_MODEL ? 'toate modelele' : row.model} — intrare ${usdWords(input.usd_micros)} USD, ieșire ${usdWords(output.usd_micros)} USD pe milion de tokenuri (versiunea ${Math.max(Number(input.version) || 1, Number(output.version) || 1)}).`;
}

/* ------------------------------------------------------------ the paid steps of a film (2026-10-01) */

/** The values of the Owner's rule for a film's paid steps (backend app.models PAID_MEDIA_APPROVALS). */
export const PAID_MEDIA_APPROVALS = /** @type {const} */ (['EVERY_PAID_STEP', 'OVER_USD', 'MODE']);

/**
 * The Owner's own rule for a film's paid steps (stills, the hero test shot, the motion), as the
 * shooting sheet carries it (`owner_rule`: paid_media_approval, over_usd). Read the way the backend
 * reads it (services.paid_media_policy): a missing or unknown value, or OVER_USD without a finite
 * threshold of 0 or more, is the strictest rule, never MODE. Only he changes it; the page only says it.
 * @param {any} rule
 */
export function paidMediaRuleWords(rule) {
  const value = String(rule?.paid_media_approval || '');
  const over = rule?.over_usd;
  if (value === 'OVER_USD' && over !== null && over !== undefined && Number.isFinite(Number(over)) && Number(over) >= 0) {
    const usd = Number(over).toLocaleString('ro-RO', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `Regula ta: un pas plătit de peste ${usd} USD îți cere aprobarea; unul mai mic urmează modul studioului.`;
  }
  if (value === 'MODE') return 'Regula ta: pașii plătiți urmează modul studioului.';
  return 'Regula ta: fiecare pas plătit al unui film îți cere aprobarea, în orice mod al studioului.';
}

/* ------------------------------------------------------------------------- about the studio */

/** The module words the drawer used (main.js), kept for Setări → Despre studio. */
export const MODULE_STATE = { IMPLEMENTED: 'Implementat', PARTIAL: 'Parțial', NOT_IMPLEMENTED: 'Neimplementat' };

/**
 * The module list in one line, for the tab's summary.
 * @param {Record<string, string>|null|undefined} modules
 */
export function modulesSummary(modules) {
  const values = Object.values(modules || {}).map(String);
  const n = (/** @type {string} */ s) => values.filter((v) => v === s).length;
  const parts = [];
  const done = n('IMPLEMENTED');
  const part = n('PARTIAL');
  const none = n('NOT_IMPLEMENTED');
  if (done) parts.push(`${done} ${done === 1 ? 'implementat' : 'implementate'}`);
  if (part) parts.push(`${part} parțial`);
  if (none) parts.push(`${none} ${none === 1 ? 'neimplementat' : 'neimplementate'}`);
  return parts.join(' · ') || '—';
}
