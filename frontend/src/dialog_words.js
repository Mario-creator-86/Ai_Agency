/**
 * The dialogs' states, said in Romanian (glossary W26).
 *
 * The eight dialogs, the inspector and the mail printed the backend's enums as words: «Stare:
 * SELECTED», «QC: PASSED», «IDLE», «OPEN», «PENDING · NECHELTUIBIL». A stranger reads a code
 * beside a Romanian sentence as a page nobody finished. Here each state the page prints is said
 * in the word that agrees with the noun it is said of; the enum itself stays in `data-*`, in the
 * element's title and in everything the page posts. A value this page has never heard of passes
 * through lower-cased with spaces rather than being guessed into a known one. Sentences the
 * backend or a model wrote are not passed through here at all: they stay as written.
 *
 * Pure: no document, so `node --test` loads it.
 */
import { amount } from './numbers.js';
import { statusLabel, runtimeLabel } from './ledger.js';

/** @param {unknown} value */
export function codeWords(value) {
  const text = String(value ?? '').trim();
  return text ? text.replace(/_/g, ' ').toLowerCase() : '—';
}

/** @param {Record<string, string>} map @returns {(value: unknown) => string} */
const lookup = (map) => (value) => map[String(value ?? '').toUpperCase()] ?? codeWords(value);

/** A topic (subiect, masculine). */
export const topicStatus = lookup({ PROPOSED: 'propus', RESEARCHED: 'documentat', SELECTED: 'ales', REJECTED: 'respins' });

/** A storyboard (neuter, agrees as the masculine). */
export const storyboardStatus = lookup({
  DRAFT: 'ciornă', APPROVED: 'aprobat', RENDERING: 'se randează', RENDERED: 'randat', REJECTED: 'respins', FAILED: 'eșuat',
});

/** The ink a storyboard's state is set in: green only for what went right. @param {unknown} status */
export function storyboardTone(status) {
  const key = String(status ?? '').toUpperCase();
  if (key === 'REJECTED' || key === 'FAILED') return 'text-error';
  if (key === 'RENDERED' || key === 'APPROVED') return 'text-accent';
  return '';
}

const SHOT = lookup({
  MEDIUM: 'plan mediu', WIDE: 'plan larg', WIDE_ESTABLISHING: 'plan general', MEDIUM_TWO_SHOT: 'plan mediu în doi',
  MEDIUM_CLOSEUP: 'plan apropiat', CLOSEUP: 'prim-plan', CLOSE_UP: 'prim-plan',
});
const VISUAL = lookup({ MOTION_GRAPHIC: 'grafică animată', GENERATED_IMAGE: 'imagine generată', STOCK_FOOTAGE: 'imagini de arhivă' });

/** A scene's shot size and picture kind, in film words. @param {unknown} shot @param {unknown} visual */
export function shotWords(shot, visual) {
  return [shot ? SHOT(shot) : '', visual ? VISUAL(visual) : ''].filter(Boolean).join(' · ');
}

/** Quality control (controlul, masculine): «QC: a trecut». */
export const qcWord = lookup({ PASSED: 'a trecut', FAILED: 'nu a trecut' });

/** A character's consistency (feminine). */
export const consistencyWord = lookup({
  UNVERIFIED: 'neverificată', CONSISTENT: 'verificată', DRIFT_SUSPECTED: 'abatere suspectată', CHANGE_PENDING: 'schimbare în așteptare',
});

/** A channel's type. */
export const channelTypeWord = lookup({ MAIN_FACTUAL: 'Shorts factuale', OFFICE_SERIAL: 'Office Serial' });

/** A publication (the film, masculine). */
export const publicationStatus = lookup({
  PUBLISHED: 'publicat', STARTED: 'în curs', FAILED_RETRYABLE: 'eșuat, se reîncearcă', FAILED_FINAL: 'eșuat definitiv',
  REMOTE_UNKNOWN: 'necunoscut la YouTube',
});

/** An employee's standing in the company (statut). */
export const lifecycleWord = lookup({ ACTIVE: 'activ', PAUSED: 'în pauză', SUSPENDED: 'suspendat', TERMINATED: 'concediat' });

/**
 * Which of the inspector's two lifecycle controls is a real change for this employee (W27). The
 * backend accepts «resume» on an active employee and records an «agent.resumed» that changed
 * nothing, so the page offers pause only to one who works and resume only to one who does not.
 * @param {unknown} lifecycle
 * @returns {{pause: boolean, resume: boolean}}
 */
export function lifecycleActs(lifecycle) {
  const state = String(lifecycle || 'ACTIVE').toUpperCase();
  return { pause: state === 'ACTIVE', resume: state === 'PAUSED' || state === 'SUSPENDED' };
}

/** An employee's work, the same words the name tag draws (part three). @param {unknown} state */
export function workWord(state) {
  return runtimeLabel(String(state || 'IDLE'));
}

/** A run or a stage (feminine), part one's list. @param {unknown} status */
export function runStatusWord(status) {
  const key = String(status ?? '').toUpperCase();
  const word = statusLabel(key);
  return word && word !== key ? word : codeWords(status);
}

/** The preflight (verificare, feminine). */
export const preflightWord = lookup({ READY: 'gata', DEGRADED: 'cu limitări', BLOCKED: 'blocantă' });

/** A Director's decision, as an imperative to the one who acts. */
export const decisionWord = lookup({
  SCALE: 'Extinde', CONTINUE: 'Continuă', ITERATE: 'Corectează', EXPERIMENT: 'Experimentează', HOLD: 'Așteaptă',
  COOLDOWN: 'Pauză', REDUCE: 'Reduce', STOP: 'Oprește', NEEDS_MORE_DATA: 'Mai multe date',
});

/** A decision's own state (feminine). */
export const decisionStateWord = lookup({ OPEN: 'deschisă', CLOSED: 'închisă', SUPERSEDED: 'înlocuită', RESOLVED: 'rezolvată' });

/** A stage of the company's pipeline, as the backend names its bottleneck. */
export const pipelineStageWord = lookup({
  RESEARCH: 'cercetare', WRITING: 'scriere', APPROVAL: 'aprobare', PRODUCTION: 'producție', PUBLISHING: 'publicare',
});

/**
 * What a decision is about, from the backend's matter keys (agents/command.py): `renders_failed`,
 * `bottleneck_<stage>`, `cold_start_<the channel id's first 8>`.
 * @param {unknown} key @param {Map<string, string>} [channels] the first 8 of a channel id → its name
 */
export function matterWords(key, channels) {
  const text = String(key ?? '');
  if (text === 'renders_failed') return 'randări eșuate';
  const neck = /^bottleneck_(.+)$/.exec(text);
  if (neck) return `gâtuire la ${pipelineStageWord(neck[1])}`;
  const cold = /^cold_start_(.+)$/.exec(text);
  if (cold) {
    const name = channels && channels.get(cold[1]);
    return name ? `pornire la rece · ${name}` : 'pornire la rece';
  }
  return codeWords(text);
}

/** Confidence (încredere, feminine). */
export const confidenceWord = lookup({ LOW: 'scăzută', MEDIUM: 'medie', HIGH: 'ridicată' });

/** What limits growth. */
export const constraintWord = lookup({ NO_DATA: 'fără date', NONE_VISIBLE: 'nicio limită vizibilă' });

/** A budget (masculine). */
export const budgetStateWord = lookup({
  OK: 'în limită', WARN: 'peste avertizare', WARNING: 'peste avertizare', EXCEEDED: 'peste limită', BLOCKED: 'peste limită',
});

/** The backend's tag on money that cannot be spent; its own Romanian labels stay. @param {unknown} label */
export function moneyTagWord(label) {
  const key = String(label ?? '').toUpperCase();
  return { PENDING: 'NEDECONTAT', FORECAST: 'PROGNOZĂ' }[key] || String(label ?? '');
}

/** An account's type. */
export const accountTypeWord = lookup({
  ASSET: 'activ', LIABILITY: 'datorie', EQUITY: 'capital propriu', REVENUE: 'venit', EXPENSE: 'cheltuială',
});

/**
 * An account's type and its money class on one line, said once when both name the same thing
 * («datorie · Datorie» was the debt account's line). @param {unknown} type @param {string} classLabel
 */
export function accountLine(type, classLabel) {
  const word = accountTypeWord(type);
  return word.toLowerCase() === String(classLabel || '').toLowerCase() ? String(classLabel) : `${word} · ${classLabel}`;
}

/** A provider's key as its product name (glossary part one: these are never translated). */
export const providerName = (/** @type {unknown} */ key) =>
  ({ runway: 'Runway', elevenlabs: 'ElevenLabs', ollama: 'Ollama', youtube: 'YouTube', ffmpeg: 'FFmpeg' })[String(key ?? '').toLowerCase()] || String(key ?? '');

/** A letter (mesaj, masculine), part two. */
export const letterStateWord = lookup({ OPEN: 'deschis', ANSWERED: 'răspuns', RESOLVED: 'rezolvat' });

/** When an employee's extra models are used, in the select's own words. */
export const policyWord = lookup({
  IMPORTANT_ONLY: 'numai pentru sarcini importante', LOW_CONFIDENCE: 'când încrederea este scăzută', ALWAYS: 'întotdeauna',
  MANUAL: 'numai la cerere explicită',
});

/** The Owner, where the data names him, is the Proprietar on the page. @param {unknown} name */
export function ownerName(name) {
  const text = String(name ?? '');
  return /^owner$/i.test(text.trim()) ? 'Proprietar' : text;
}

/** A duration in seconds: «4,8 s». @param {unknown} value */
export function seconds(value) {
  if (value === null || value === undefined || value === '') return '—';
  const text = String(value).trim();
  if (!/^\d+(\.\d+)?$/.test(text)) return '—';
  return `${amount(text)} s`;
}

/** A frame's size: «1080×1920». @param {unknown} width @param {unknown} height */
export function frameSize(width, height) {
  const w = Number(width);
  const h = Number(height);
  return w > 0 && h > 0 ? `${w}×${h}` : '—';
}

/** An ISO day as Romanian writes it: «12.09.2026». @param {unknown} value */
export function isoDay(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ''));
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(value ?? '') || '—';
}

/**
 * W28: an employee's place in the building, in the dialogs' and face cards' own words (glossary
 * W28): the inspector's eyebrow, where the role code stood. The manifest's zone of the desk.
 */
export const ZONE_PLACE = {
  director_suite: 'DIRECȚIUNE · L4',
  research_lab: 'CERCETARE · L3',
  factcheck_room: 'VERIFICAREA FAPTELOR · L3',
  script_room: 'CONȚINUT · L2',
  publish_desk: 'DISTRIBUȚIE · L2',
  audio_booth: 'PRODUCȚIE AUDIO · L1',
  video_studio: 'RANDARE · L1',
  server_corner: 'SERVERE · S1',
  lobby: 'RECEPȚIE',
  accounting_office: 'TREZORERIE · S2',
  ad_shop: 'AI SPACE · S3',
};

/**
 * The place of a desk: its seat's zone in the manifest; a desk the manifest does not seat, or no
 * desk at all, is the headquarters itself.
 * @param {any} manifest @param {string|null|undefined} deskId
 */
export function deskPlace(manifest, deskId) {
  const seat = manifest && manifest.seats && deskId ? manifest.seats[deskId] : null;
  const zone = seat && typeof seat.zone === 'string' ? seat.zone : '';
  return /** @type {Record<string, string>} */ (ZONE_PLACE)[zone] || 'SEDIUL · ANGAJAȚI';
}

/**
 * W28: what every scene's picture prompt ends with, word for word, said once. The backend writes
 * each scene's prompt as its own picture and then the same directions (composition, motion, style,
 * what to avoid) for all of them; five boxes repeated the same eighty words. The shared end is the
 * longest common ending that starts a sentence («Composition: …»); nothing is reworded, and a
 * scene's own words are never cut (at least one character of its own must remain).
 * @param {string[]} texts
 * @returns {{heads: string[], tail: string}} each prompt without the shared end, and the end ('' when none)
 */
export function sharedTail(texts) {
  const list = (texts || []).map((t) => String(t ?? ''));
  const none = { heads: list, tail: '' };
  if (list.length < 2) return none;
  let n = 0;
  const shortest = Math.min(...list.map((t) => t.length));
  while (n < shortest && list.every((t) => t[t.length - 1 - n] === list[0][list[0].length - 1 - n])) n++;
  if (n < 40) return none;
  const candidate = list[0].slice(list[0].length - n);
  // start the shared end at a sentence: a capital letter after «. », or the very start of the
  // common part when every prompt has a sentence end just before it
  const endsBefore = list.every((t) => /\.\s*$/.test(t.slice(0, t.length - n)));
  let start = -1;
  for (let i = 0; i < candidate.length; i++) {
    if (!/[A-Z]/.test(candidate[i])) continue;
    const before = i === 0 ? '' : candidate.slice(0, i);
    if ((i === 0 && endsBefore) || (i > 0 && /\.\s+$/.test(before))) { start = i; break; }
  }
  if (start < 0) return none;
  const tail = candidate.slice(start).trim();
  if (tail.length < 40) return none;
  const heads = list.map((t) => t.slice(0, t.length - candidate.length + start).trimEnd());
  if (heads.some((h) => !h)) return none;
  return { heads, tail };
}
