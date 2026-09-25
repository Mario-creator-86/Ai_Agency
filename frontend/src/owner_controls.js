import { channelTypeWord } from './dialog_words.js';

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
 * @typedef {{kind: string, model: string, input: SidePrice|null, output: SidePrice|null, priced: boolean}} PriceRow
 */

/**
 * One row per model: the ones the preflight found unpriced, then every model the books price per
 * token, each with what each side costs now and its version.
 * @param {any} preflight /runbook/preflight
 * @param {any[]|null|undefined} prices /economy/prices .prices (active)
 * @returns {PriceRow[]}
 */
export function tokenPriceRows(preflight, prices) {
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
  for (const p of Array.isArray(prices) ? prices : []) {
    if (!p || p.active === false || !TOKEN_UNITS.includes(p.unit)) continue;
    const r = row(String(p.provider_kind || ''), String(p.resource || ''));
    const side = { usd: String(p.usd ?? ''), usd_micros: Number(p.usd_micros), version: Number(p.version) || 1 };
    if (p.unit === 'per_1m_input_tokens') r.input = side;
    else r.output = side;
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
  return `Salvat: ${row.kind} · ${row.model} — intrare ${usdWords(input.usd_micros)} USD, ieșire ${usdWords(output.usd_micros)} USD pe milion de tokenuri (versiunea ${Math.max(Number(input.version) || 1, Number(output.version) || 1)}).`;
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
