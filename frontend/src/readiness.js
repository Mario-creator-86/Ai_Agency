/**
 * What the panel is allowed to say about a check and about a figure.
 *
 * Two overstatements, both measured on the page before this module existed. The preflight
 * printed every failing check as either BLOCKING or DEGRADES, which was true while the only
 * two severities were those; `serial_channel` and an unlocked `character_references` are now
 * INFORMATIONAL and can fail, so the Owner read a red "DEGRADES" about a channel he has
 * deliberately not created. And the approvals card printed «Cost: 4.2 USD» for a question
 * whose estimate had counted the narration as nothing, because the caveat the media stage
 * computed lived only in the request's evidence line.
 *
 * They live here rather than in `main.js` for the reason `governance.js` gives: `main.js`
 * touches the document the moment it is imported and therefore cannot be loaded by
 * `node --test`, and every judgement below is a word the Owner reads.
 *
 * The check names and severities are `backend/app/runbook/preflight.py`; the caveat's first
 * words are `UNPRICED_CAVEAT_PREFIX` in `backend/app/economy/budget.py`.
 */

/**
 * Preflight check names, as the Owner would say them.
 *
 * Every name `run_preflight` can emit has a line here, including the five that name what only
 * he can supply and the one that reports the mode he chose: a check shown by its code name
 * reads like a fault in the program rather than a question about his studio.
 *
 * The map is walked against `backend/app/runbook/preflight.py` by
 * `tests/test_first_day_adversary.py`, not listed by hand — the one name missing here when
 * that test was written, `youtube_channel_binding`, was the one nobody had thought to list.
 *
 * @type {Record<string, string>}
 */
export const RUNBOOK_CHECK_LABELS = {
  stop_autonomy: 'STOP autonomie',
  autonomy_mode: 'Modul de autonomie',
  llm_provider: 'Model de limbaj',
  agents: 'Angajați disponibili',
  render_engine: 'Motor de randare (FFmpeg)',
  media_inspection: 'Inspecția fișierelor media (FFprobe)',
  research_sources: 'Site-uri autorizate pentru documentare',
  image_provider: 'Furnizor de imagine',
  voice_provider: 'Furnizor de voce',
  publishing: 'Publicare',
  youtube_channel_binding: 'Sloturi de canal legate de YouTube',
  youtube_upload_access: 'Dreptul de a încărca pe YouTube',
  youtube_statistics_access: 'Accesul la statisticile YouTube',
  spending_budget: 'Buget de cheltuieli',
  daily_budget_films: 'Filmele zilei în bugetul zilnic',
  model_prices: 'Prețurile modelelor',
  vision_capability: 'Angajat care poate privi',
  character_references: 'Imaginile de referință ale personajelor',
  serial_channel: 'Canalul serialului',
};

/** @param {string} name */
export function checkLabel(name) {
  return RUNBOOK_CHECK_LABELS[name] || name;
}

/**
 * The word beside a check, which must mean what the check's severity means.
 *
 * INFORMATIONAL is the whole point: it neither blocks the day nor degrades it, so it reads as
 * information whether it passed or failed. A severity this page has never heard of is shown
 * as it came rather than rounded into one of the three — a new severity read as "DEGRADES"
 * would be this same defect again.
 *
 * @param {{ok?: boolean, severity?: string}} check
 */
export function checkVerdictWord(check) {
  if (check.ok) return 'OK';
  switch (String(check.severity || '').toUpperCase()) {
    case 'BLOCKING':
      return 'BLOCHEAZĂ';
    case 'DEGRADING':
      return 'DEGRADEAZĂ';
    case 'INFORMATIONAL':
      return 'INFORMATIV';
    default:
      return String(check.severity || 'NECUNOSCUT');
  }
}

/**
 * The classes that colour it. A failing INFORMATIONAL check gets its own class rather than
 * falling through to the degrading one's amber, and an unknown severity gets none of the
 * three, so it is neutral rather than wrongly alarming.
 *
 * @param {{ok?: boolean, severity?: string}} check
 */
export function checkClassName(check) {
  if (check.ok) return 'runbook-check rb-ok';
  const severity = String(check.severity || '').toUpperCase();
  const known = ['BLOCKING', 'DEGRADING', 'INFORMATIONAL'].includes(severity);
  return `runbook-check rb-fail${known ? ` rb-${severity.toLowerCase()}` : ''}`;
}

/** The first words of the sentence the studio says about a figure it could not complete. */
export const UNPRICED_CAVEAT_PREFIX = 'estimare incompletă';

/**
 * The caveat the studio wrote about its own estimate, read back out of a request's evidence.
 *
 * `ApprovalRequest` carries a cost and an evidence line and no column for "this figure is not
 * the whole film", so the media stage writes the sentence into the evidence and the
 * Accountant's letter and this card read it back from there — the same way, by its first
 * words. A question whose figure was whole yields "", because a doubt shown about every cost
 * teaches the Owner to read past the one that matters.
 *
 * @param {string | null | undefined} evidence
 */
export function approvalCaveat(evidence) {
  if (!evidence) return '';
  const start = String(evidence).indexOf(UNPRICED_CAVEAT_PREFIX);
  if (start < 0) return '';
  return String(evidence)
    .slice(start)
    .replace(/[)\s]+$/, '');
}

/**
 * A check's line: its message, then what its detail adds.
 *
 * W31: the research check's detail begins with its own message and then names the sites that
 * cannot be read; printed whole, the Owner read the same sentence twice. The repeat is dropped
 * and only what follows it is kept; both sentences stay exactly as the backend wrote them.
 *
 * @param {{message?: string | null, detail?: string | null}} check
 */
export function checkLine(check) {
  const message = String(check.message || '').trim();
  let detail = String(check.detail || '').trim();
  if (message && detail.startsWith(message)) {
    const rest = detail.slice(message.length);
    // only a whole repeat: «8 activi» is not repeated inside «8 activii»
    if (rest === '' || /^\s/.test(rest)) detail = rest.trim();
  }
  if (!message) return detail;
  return detail ? `${message} · ${detail}` : message;
}

/** The daily job's name on the page; its code (`daily_main`) stays in the title. */
export const SCHEDULE_TITLE = 'Ziua programată';

/**
 * When the daily job will next fire, or null when it will not.
 *
 * W31: a stopped job keeps the next time it had when it was stopped, and the panel printed
 * «Următoarea rulare: 18.09.2026» on 25.09 beside «Programarea este oprită». A stopped job
 * fires nothing, so it has no next run.
 *
 * @param {{is_active?: boolean, next_run_at?: string | null}} job
 */
export function scheduleNextRun(job) {
  if (!job.is_active) return null;
  return job.next_run_at || null;
}

/* ==========================================================================================
 * W32 — THE PREFLIGHT AS A GAME'S CHECKLIST
 * ==========================================================================================
 * The release judge read the preflight as a console: nineteen cards of the backend's paragraphs,
 * a passing line at the weight of the one that costs the day, API routes and scope lists printed
 * whole. It is now a checklist. The lines that fail stand first (the backend's first stop, then
 * blocking, then degrading, then a severity the page does not know), each one row: its state in
 * words, colour and shape, its name, the backend's message, and a key to the place in the page
 * that fixes it. The informational lines that fail follow; the passing lines are one quiet row
 * each. Every detail is behind «Detalii». Order, state and place come from the check's code,
 * `ok` and `severity`; no sentence is parsed, and every sentence is printed as it came.
 */

/**
 * The places in the page that fix a line: a door (and a section or tab of it), a Settings tab, or
 * the dock's AUTONOMIE switch. Each label is the place's own heading.
 * @type {Record<string, {label: string, door: string, tab?: string, section?: string}>}
 */
export const FIX_PLACES = {
  autonomy_switch: { label: 'comutatorul AUTONOMIE', door: 'autonomy_switch' },
  'settings:llm': { label: 'Setări · Furnizori AI', door: 'settings', tab: 'llm' },
  'settings:agents': { label: 'Setări · Angajați', door: 'settings', tab: 'agents' },
  'settings:media': { label: 'Setări · Video și sunet', door: 'settings', tab: 'media' },
  'settings:social': { label: 'Setări · Conturi și e-mail', door: 'settings', tab: 'social' },
  research: { label: 'Cercetare · Surse și afirmații', door: 'research-modal', section: 'rs-sources' },
  publishing: { label: 'Distribuție · Sloturi de canal', door: 'publishing-modal', section: 'channels-list' },
  treasury: { label: 'Trezorerie · Buget și cheltuieli', door: 'treasury-modal', section: 'tr-budget' },
  characters: { label: 'Media · Character Bible', door: 'media-modal', tab: 'characters', section: 'media-characters-section' },
};

/**
 * Which place fixes each check, by its code (`backend/app/runbook/preflight.py`). A check with no
 * entry has no place in the page: FFmpeg and FFprobe are installed on the studio's machine, the
 * token prices and the serial's right to approve episodes are set through the API only.
 * @type {Record<string, string>}
 */
export const CHECK_FIX = {
  stop_autonomy: 'autonomy_switch',
  llm_provider: 'settings:llm',
  agents: 'settings:agents',
  vision_capability: 'settings:agents',
  research_sources: 'research',
  image_provider: 'settings:media',
  voice_provider: 'settings:media',
  publishing: 'settings:social',
  youtube_upload_access: 'settings:social',
  youtube_statistics_access: 'settings:social',
  youtube_channel_binding: 'publishing',
  spending_budget: 'treasury',
  daily_budget_films: 'treasury',
  character_references: 'characters',
};

/**
 * The backend's places (`backend/app/runbook/preflight.py` PLACES, W32): a door by its masthead
 * room, a Settings tab, the dock's AUTONOMIE switch. `machine` (the studio's computer) and
 * `not_on_page` (the API only) are no place in the page, so they get no key.
 * @type {Record<string, string>}
 */
export const BACKEND_DOORS = {
  research: 'research-modal',
  media: 'media-modal',
  publishing: 'publishing-modal',
  workforce: 'workforce-modal',
  story: 'story-modal',
  treasury: 'treasury-modal',
  autonomy_switch: 'autonomy_switch',
};

/**
 * @typedef {{label: string, door: string, tab?: string, section?: string}} FixPlace
 */

/**
 * The place that fixes a failing line, or null: a passing line needs no key, and a line nothing in
 * the page can fix gets none rather than a key to a place that cannot help. The backend's own
 * `place`, `place_label` and `place_section` are read first (W32; the label is its words, as its
 * sentence names the place); a backend that does not send them yet (the Owner's running studio
 * before a restart) is read by the check's code (CHECK_FIX).
 * @param {{name?: string, ok?: boolean, place?: string|null, place_label?: string|null, place_section?: string|null}} check
 * @returns {FixPlace|null}
 */
export function fixPlaceOf(check) {
  if (!check || check.ok) return null;
  if (Object.prototype.hasOwnProperty.call(check, 'place')) {
    const place = String(check.place || '');
    const label = String(check.place_label || '').trim();
    const section = check.place_section ? String(check.place_section) : undefined;
    if (place.startsWith('settings:')) {
      const tab = place.slice('settings:'.length);
      return { label: label || FIX_PLACES[place]?.label || 'Setări', door: 'settings', tab };
    }
    const door = BACKEND_DOORS[place];
    if (!door || !label) return null;
    return {
      label,
      door,
      ...(section === 'media-characters-section' ? { tab: 'characters' } : {}),
      ...(section ? { section } : {}),
    };
  }
  const key = CHECK_FIX[String(check.name || '')];
  return key ? FIX_PLACES[key] || null : null;
}

/**
 * What the sentence no longer says (the backend's `technical`: routes, settings, scopes, fields,
 * answers, paths), for the line's tooltip. "" when it sends none.
 * @param {{technical?: Record<string, unknown>}} check
 */
export function technicalNote(check) {
  const t = check && check.technical && typeof check.technical === 'object' ? check.technical : null;
  if (!t) return '';
  return Object.values(t).flatMap((v) => (Array.isArray(v) ? v.map(String) : [])).filter(Boolean).join(' · ');
}

/**
 * What a check's detail adds to its message (W31's rule): a detail that begins with the whole
 * message keeps only what follows it; both stay the backend's words.
 * @param {{message?: string | null, detail?: string | null}} check
 */
export function checkDetailAdds(check) {
  const message = String(check.message || '').trim();
  const detail = String(check.detail || '').trim();
  if (message && detail.startsWith(message)) {
    const rest = detail.slice(message.length);
    if (rest === '' || /^\s/.test(rest)) return rest.trim();
  }
  return detail;
}

/**
 * @typedef {{name: string, label: string, word: string, tone: 'blocking'|'degrading'|'info'|'ok'|'unknown',
 *   message: string, detail: string, fix: FixPlace|null, technical: string, first: string}} ChecklistRow
 */

/**
 * The checklist's three groups, from the checks' codes, `ok` and `severity`.
 * @param {{checks?: any[], first_stop?: string | null}} preflight
 * @returns {{attention: ChecklistRow[], notes: ChecklistRow[], ok: ChecklistRow[]}}
 */
export function preflightChecklist(preflight) {
  const checks = Array.isArray(preflight && preflight.checks) ? preflight.checks : [];
  const firstStop = preflight && preflight.first_stop ? String(preflight.first_stop) : '';
  /** @param {any} check @returns {ChecklistRow} */
  const row = (check) => {
    const severity = String(check.severity || '').toUpperCase();
    /** @type {ChecklistRow['tone']} */
    const tone = check.ok ? 'ok'
      : severity === 'BLOCKING' ? 'blocking'
        : severity === 'DEGRADING' ? 'degrading'
          : severity === 'INFORMATIONAL' ? 'info' : 'unknown';
    const place = fixPlaceOf(check);
    const name = String(check.name || '');
    return {
      name,
      label: checkLabel(name),
      word: checkVerdictWord(check),
      tone,
      message: String(check.message || '').trim(),
      detail: checkDetailAdds(check),
      fix: place,
      technical: technicalNote(check),
      first: !check.ok && firstStop && name === firstStop
        ? (severity === 'BLOCKING' ? 'Primul punct blocant' : 'Ziua nu ajunge întreagă')
        : '',
    };
  };
  /** @param {ChecklistRow} r */
  const rank = (r) => (r.first ? -1 : r.tone === 'blocking' ? 0 : r.tone === 'degrading' ? 1 : 2);
  const rows = checks.map((c, i) => ({ i, r: row(c) }));
  const attention = rows
    .filter(({ r }) => r.tone === 'blocking' || r.tone === 'degrading' || r.tone === 'unknown' || Boolean(r.first))
    .sort((a, b) => rank(a.r) - rank(b.r) || a.i - b.i)
    .map(({ r }) => r);
  return {
    attention,
    notes: rows.filter(({ r }) => r.tone === 'info' && !r.first).map(({ r }) => r),
    ok: rows.filter(({ r }) => r.tone === 'ok').map(({ r }) => r),
  };
}

/** The shape beside a state's word, so the state is never said by colour alone. */
const TONE_SHAPE = { blocking: '■', degrading: '▲', info: '●', unknown: '●', ok: '✓' };

/**
 * The checklist's markup. A failing line: its mark, its name and the backend's message, a key to
 * the place that fixes it, and «Detalii» when the detail adds something. A passing line: one quiet
 * row, a disclosure of its own when it has more to say.
 * @param {{attention: ChecklistRow[], notes: ChecklistRow[], ok: ChecklistRow[]}} list
 * @param {(s: unknown) => string} escape
 */
export function checklistHtml(list, escape) {
  const mark = (/** @type {ChecklistRow} */ r) =>
    `<span class="pf-mark" data-tone="${r.tone}"><span class="pf-shape" aria-hidden="true">${TONE_SHAPE[r.tone]}</span><span class="pf-word">${escape(r.word)}</span></span>`;
  const more = (/** @type {ChecklistRow} */ r) => r.detail
    ? `<details class="pf-more"><summary class="pf-more-key">Detalii</summary>
          <p class="pf-detail">${escape(r.detail)}</p></details>`
    : '';
  const failing = (/** @type {ChecklistRow} */ r) => `
      <article class="pf-row pf-fail" data-tone="${r.tone}" data-check="${escape(r.name)}">
        ${mark(r)}
        <div class="pf-body">
          ${r.first ? `<span class="pf-first">${escape(r.first)}</span>` : ''}
          <h4 class="pf-name"${r.technical ? ` title="${escape(r.technical)}"` : ''}>${escape(r.label)}</h4>
          ${r.message ? `<p class="pf-message">${escape(r.message)}</p>` : ''}
          ${more(r)}
        </div>
        ${r.fix ? `<button type="button" class="secondary pf-fix" data-door="${escape(r.fix.door)}"${r.fix.tab ? ` data-tab="${escape(r.fix.tab)}"` : ''}${r.fix.section ? ` data-section="${escape(r.fix.section)}"` : ''}>${r.fix.door === 'autonomy_switch' ? 'Arată' : 'Deschide'} ${escape(r.fix.label)}</button>` : ''}
      </article>`;
  const passing = (/** @type {ChecklistRow} */ r) => r.detail
    ? `
      <details class="pf-row pf-ok" data-tone="ok" data-check="${escape(r.name)}">
        <summary class="pf-ok-line">${mark(r)}<span class="pf-name">${escape(r.label)}</span><span class="pf-message">${escape(r.message)}</span><span class="pf-more-key">Detalii</span></summary>
        <p class="pf-detail">${escape(r.detail)}</p>
      </details>`
    : `
      <div class="pf-row pf-ok" data-tone="ok" data-check="${escape(r.name)}">
        <div class="pf-ok-line">${mark(r)}<span class="pf-name">${escape(r.label)}</span><span class="pf-message">${escape(r.message)}</span></div>
      </div>`;
  const group = (/** @type {string} */ title, /** @type {string} */ kind, /** @type {ChecklistRow[]} */ rows, /** @type {(r: ChecklistRow) => string} */ one) => rows.length
    ? `<section class="pf-group" data-group="${kind}">
        <h4 class="pf-group-head"><span class="pf-group-title">${title}</span>
          <span class="pf-count">${rows.length}</span></h4>
        <div class="pf-rows">${rows.map(one).join('')}</div>
      </section>`
    : '';
  return group('De rezolvat', 'attention', list.attention, failing)
    + group('De știut', 'notes', list.notes, failing)
    + group('În regulă', 'ok', list.ok, passing);
}
