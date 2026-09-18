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
  spending_budget: 'Buget de cheltuieli',
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
