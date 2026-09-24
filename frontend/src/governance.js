import { amount } from './numbers.js';
/**
 * What the Owner's panel has to say about the studio's own authority.
 *
 * Three things the API has been answering that nothing on the page read: which autonomy mode
 * the studio is really in, which actions a SUPERVISED studio stopped to ask about, and which
 * reference pictures a character actually has. They live here rather than in `main.js` because
 * `main.js` touches the document the moment it is imported and therefore cannot be loaded by
 * `node --test`; every judgement below — what a mode means, whether a promotion is possible,
 * what an unpriced action costs, how long a request still stands — is a decision the Owner
 * reads, so it is tested.
 *
 * The wording comes from `docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md`,
 * `31_GOVERNANCE_APPROVAL_POLICY.md` and `backend/app/services.py` (`MODE_MEMORY`,
 * `ACTION_RISK_TIERS`), so the page tells the Owner the same thing the agents were told.
 */

/** The three modes the backend's `AutonomyMode` accepts, lowest authority first. */
export const AUTONOMY_MODES = /** @type {const} */ (['MANUAL', 'SUPERVISED', 'AUTONOMOUS_CEO']);

/** Their rank, so a promotion can be told from a reduction without asking the server. */
const AUTONOMY_RANK = { MANUAL: 0, SUPERVISED: 1, AUTONOMOUS_CEO: 2 };

/** @type {Record<string, string>} Short names for the switch itself. */
export const MODE_LABEL = {
  MANUAL: 'Manual',
  SUPERVISED: 'Supravegheat',
  AUTONOMOUS_CEO: 'CEO autonom',
};

/**
 * What each mode means for the day, in the Owner's language.
 *
 * The same sentences `MODE_MEMORY` writes into every agent's memory when the mode moves, so
 * the panel and the studio cannot describe the same day differently.
 *
 * @type {Record<string, string>}
 */
export const MODE_MEANING = {
  MANUAL:
    'Agenții pregătesc și analizează, iar Proprietarul aprobă trecerile între etape: ziua merge ' +
    'mai departe, dar etapele peste treapta T1 rămân nefăcute și nimic nu iese din studio.',
  SUPERVISED:
    'Etapele interne de rutină merg singure; o scriere în afara studioului nu se execută, ci ' +
    'devine o cerere de aprobare pe care o vezi mai jos.',
  AUTONOMOUS_CEO:
    'Directoarea execută singură treptele T0–T3 în limitele politicii; treapta T4 rămâne a ' +
    'Proprietarului, iar porțile dure rămân la fel de închise.',
};

/**
 * The risk tiers of 31, as the Owner reads them on a request.
 *
 * @type {Record<string, string>}
 */
const TIER_MEANING = {
  T0: 'Doar citire: analitice, starea furnizorilor, căutare în surse publice.',
  T1: 'Scriere internă reversibilă: o schiță, o prioritate schimbată, o măsurătoare.',
  T2: 'Schimbare internă materială: modelul sau promptul unui angajat, o pagină citită din ' +
    'afară, o generare plătită în limita bugetului.',
  T3: 'Iese din studio: publicare publică, generare plătită peste prag, concediere, activarea ' +
    'unui furnizor, o schimbare publică a lumii.',
  T4: 'Numai Proprietarul: bugetul dur, Policy Kernel, credențialele, termenii legali, auditul.',
};

/** @param {unknown} tier */
export function riskTierMeaning(tier) {
  return TIER_MEANING[String(tier)] || 'Treaptă de risc necunoscută acestei pagini.';
}

/** @param {unknown} mode */
export function autonomyModeLabel(mode) {
  if (!mode) return '—';
  return MODE_LABEL[String(mode)] || String(mode);
}

/** @param {unknown} mode */
export function autonomyModeMeaning(mode) {
  return (
    MODE_MEANING[String(mode)] ||
    'Pagina nu cunoaște acest mod de autonomie; ce înseamnă pentru zi îl decide serverul.'
  );
}

/**
 * The Owner's command to move the mode.
 *
 * Shaped exactly like the environment and the stop commands the page already sends: the
 * version the snapshot was read at travels with it, so a mode set against a policy that has
 * moved is refused by the server rather than applied to a state nobody looked at.
 *
 * @param {{version?: number}|null} policy the policy from the last snapshot
 * @param {string} mode
 * @param {string} commandId a fresh UUID; the caller keeps it, so a retry is not a second command
 */
export function autonomyModeCommand(policy, mode, commandId) {
  const version = policy && Number.isSafeInteger(policy.version) ? Number(policy.version) : 0;
  if (version < 1) throw new Error('Politica nu a fost citită; reîncarcă înainte de comandă.');
  if (!AUTONOMY_MODES.includes(/** @type {any} */ (mode))) {
    throw new Error(`Mod de autonomie necunoscut: ${mode}`);
  }
  return {
    schema_version: 1,
    command_id: commandId,
    expected_version: version,
    autonomy_mode: mode,
  };
}

/**
 * Why this promotion cannot be sent, when the snapshot already says so.
 *
 * Only the stop is readable here: an open SAFE_MODE incident is not in the snapshot, so that
 * refusal is the server's to make and the panel shows the sentence it answers with. Lowering
 * the mode is never blocked — 51 calls it immediate and safe, and a safety state that blocked
 * the safer choice would be the wrong shape of safety.
 *
 * @param {{autonomy_stopped?: boolean, autonomy_mode?: string}|null} policy
 * @param {string} mode
 * @returns {string|null}
 */
export function promotionBlockedReason(policy, mode) {
  if (!policy) return null;
  const current = String(policy.autonomy_mode || 'MANUAL');
  const rank = AUTONOMY_RANK[String(mode)];
  const currentRank = AUTONOMY_RANK[current];
  if (rank === undefined || currentRank === undefined || rank <= currentRank) return null;
  if (!policy.autonomy_stopped) return null;
  return (
    'AUTONOMIA ESTE OPRITĂ: modul nu poate fi ridicat până când Proprietarul nu ridică ' +
    'oprirea. Coborârea modului rămâne permisă oricând.'
  );
}

/**
 * The approval requests, read from whichever container the route answers with.
 *
 * The listing route answers a bare array; the aliases below exist because it is being written
 * in the same run as this panel, and a field that lands under a neighbouring name should show
 * the request rather than an empty list. A cost stays `null` unless a finite number arrived: a
 * cost the studio could not compute is unknown, and `0` would say the action is free.
 *
 * @param {unknown} payload
 */
export function readApprovals(payload) {
  const rows = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object'
      ? /** @type {any} */ (payload).approvals || /** @type {any} */ (payload).requests
      : null;
  if (!Array.isArray(rows)) return [];
  return rows.filter((row) => row && typeof row === 'object').map(normaliseApproval);
}

/** @param {any} row */
function normaliseApproval(row) {
  const rawCost = row.cost_usd === undefined ? row.cost : row.cost_usd;
  const cost = typeof rawCost === 'number' && Number.isFinite(rawCost) ? rawCost : null;
  const result = String(row.result || 'PENDING');
  return {
    id: String(row.id || row.request_id || ''),
    action: String(row.action || ''),
    // What the action is in the Owner's language, when the row carries it; the bare action
    // name otherwise, because a request with no readable label is still a decision he owes.
    action_label: String(row.action_label || row.action || ''),
    subject: row.subject ? String(row.subject) : '',
    // The server's own wording for the cost, including its "necunoscut"; the page formats it
    // itself only when the row does not say.
    cost_label: row.cost_label ? String(row.cost_label) : approvalCostText(cost),
    risk_tier: String(row.risk_tier || row.tier || ''),
    requester: String(row.requester || ''),
    evidence: row.evidence ? String(row.evidence) : '',
    proposed_diff: row.proposed_diff && typeof row.proposed_diff === 'object' ? row.proposed_diff : null,
    cost_usd: cost,
    cost_known: cost !== null,
    reversible: Boolean(row.reversible),
    expires_at: row.expires_at || row.expiry || null,
    created_at: row.created_at || null,
    result,
    pending: result === 'PENDING',
  };
}

/**
 * What this action would cost the studio.
 *
 * `necunoscut` when nothing priced it — the backend keeps such a cost `None` and never zero,
 * and a panel that printed `0.00 USD` would turn "we could not price this" into "it is free".
 *
 * @param {unknown} cost
 */
export function approvalCostText(cost) {
  if (typeof cost !== 'number' || !Number.isFinite(cost)) return 'necunoscut';
  if (cost !== 0 && Math.abs(cost) < 0.01) {
    return `${amount(cost.toFixed(6).replace(/0+$/, '').replace(/\.$/, ''))} USD`;
  }
  return `${amount(cost.toFixed(2))} USD`;
}

/**
 * How long this request still stands. 31: an expired approval cannot be reused, so a request
 * that has aged out says so instead of showing a deadline that has passed.
 *
 * @param {unknown} expiresAt an ISO timestamp from the request
 * @param {number} now milliseconds since the epoch
 */
export function approvalExpiryText(expiresAt, now) {
  if (typeof expiresAt !== 'string') return 'termen necunoscut';
  const at = Date.parse(expiresAt);
  if (Number.isNaN(at)) return 'termen necunoscut';
  const left = at - now;
  if (left <= 0) return 'a expirat';
  const minutes = Math.floor(left / 60000);
  if (minutes < 60) return `expiră în ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `expiră în ${hours} h ${rest} min` : `expiră în ${hours} h`;
}

/**
 * Where the requests are read and where an answer is sent.
 *
 * Both written against the routes the governance agent is adding in this same run: the list
 * answers a bare array of pending, unexpired requests, and one command answers one of them by
 * its id in the body rather than in the path. They are named here so that a route which lands
 * under another name is one line to correct rather than a search through the panel.
 */
export const APPROVALS_PATH = '/owner/approvals';

/** The one command that answers a request; the request's id travels in the body. */
export const APPROVAL_DECISION_PATH = '/owner/approvals/decision';

/**
 * The Owner's answer to one request.
 *
 * Idempotent by `command_id` like every other Owner command, so pressing twice on a slow
 * connection is one decision rather than two authorities for one act. The command forbids
 * fields it does not declare, so nothing else is sent: the approver is the Owner by virtue of
 * the key that reached the route, and `note` is carried only when he wrote one.
 *
 * @param {string} requestId
 * @param {'APPROVED'|'REFUSED'|string} decision
 * @param {string} commandId
 * @param {string} [note] the Owner's own words, carried into what the stage reports back
 */
export function approvalDecisionCommand(requestId, decision, commandId, note) {
  if (decision !== 'APPROVED' && decision !== 'REFUSED') {
    throw new Error(`Decizie necunoscută: ${decision}`);
  }
  if (!requestId) throw new Error('Cererea nu are identificator.');
  const command = {
    schema_version: 1,
    command_id: commandId,
    approval_id: requestId,
    decision,
  };
  return note ? { ...command, note } : command;
}

/** The slots `generate_character_reference_set` produces, in the order it produces them. */
const REFERENCE_SLOTS = ['portrait', 'full_body', 'front', 'side', 'back'];

/** @type {Record<string, string>} */
const SLOT_LABEL = {
  portrait: 'Portret',
  full_body: 'Corp întreg',
  front: 'Față',
  side: 'Profil',
  back: 'Spate',
};

/**
 * Which reference pictures this character actually has.
 *
 * `reference_assets_json` declares the slots and holds `null` in the ones nothing produced, so
 * an empty slot is shown empty rather than left out: the Character Bible is what the render
 * draws a locked face from, and a missing reference is the reason a scene is refused.
 *
 * @param {{reference_assets_json?: Record<string, unknown>}|null} character
 */
export function referenceSetSummary(character) {
  const references = (character && character.reference_assets_json) || {};
  const declared = Object.keys(references);
  const slots = (declared.length ? declared : REFERENCE_SLOTS).map((slot) => ({
    slot,
    label: SLOT_LABEL[slot] || slot,
    filled: Boolean(references[slot]),
  }));
  const filled = slots.filter((s) => s.filled).length;
  return { slots, filled, total: slots.length, complete: slots.length > 0 && filled === slots.length };
}

/**
 * What the Owner is told before the studio spends image credits on a reference set.
 *
 * The Owner's rule: generation costs money and happens only when he decides it does. Nothing
 * in the day calls this route; the panel asks, in his language, and produces nothing until he
 * presses a second time.
 */
export const REFERENCE_CREDIT_WARNING =
  'Producerea setului de referință generează câte o imagine pentru fiecare slot declarat și ' +
  'consumă credite la furnizorul de imagini configurat. Costul intră în bugetul studioului. ' +
  'Apasă „Confirmă” dacă vrei să se producă acum.';
