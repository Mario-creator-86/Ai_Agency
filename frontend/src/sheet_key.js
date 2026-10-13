/**
 * WHICH FILM'S SHEET THIS IS ABOUT (PAGE_OWNER_DAY: PAGE-02).
 *
 * Under the Owner's default rule the day stops at every paid step, and the only way to the film's
 * «Foaia de filmare» was Producție media → the storyboard's card. The letter the day writes
 * (runbook/stages.py `_sheet_letter`, body_json.kind 'owner_shooting_sheet'), the approval it
 * raises (a `media.*` action whose subject is the storyboard) and the run that waits (its media
 * stage's `awaiting_owner`) all name the film; this reads the storyboard id out of any of them,
 * so each can carry a «Deschide foaia de filmare» key. Only a storyboard id is returned, never a
 * path: the page opens the sheet through its own drawer.
 *
 * Its own module so that governance.js, mail_thread.js and shooting_sheet.js can all read it
 * without importing each other.
 */

const STORYBOARD_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** @param {unknown} value */
function storyboardId(value) {
  const text = String(value ?? '');
  return STORYBOARD_ID.test(text) ? text : null;
}

/** @param {any} list */
function firstWaiting(list) {
  if (!Array.isArray(list)) return null;
  for (const item of list) {
    const id = storyboardId(item && item.storyboard_id);
    if (id) return id;
  }
  return null;
}

/**
 * The storyboard id a letter, an approval or a run names, or null.
 * - a letter: body_json.kind 'owner_shooting_sheet', or any body that carries the film's
 *   storyboard_id beside its sheet_url (the TEST letter);
 * - an approval: a `media.*` action whose context or subject is the storyboard;
 * - a run, one of its stages, or a stage's artefacts: the first `awaiting_owner` film.
 * @param {any} source
 * @returns {string|null}
 */
export function sheetKeyFor(source) {
  if (!source || typeof source !== 'object') return null;
  const body = source.body_json;
  if (body && typeof body === 'object') {
    if (body.kind === 'owner_shooting_sheet' || (body.sheet_url && body.storyboard_id)) {
      return storyboardId(body.storyboard_id);
    }
    return null;
  }
  if (typeof source.action === 'string') {
    if (!source.action.startsWith('media.')) return null;
    const context = source.context && typeof source.context === 'object' ? source.context : {};
    return storyboardId(context.storyboard_id) || storyboardId(source.subject);
  }
  if (Array.isArray(source.awaiting_owner)) return firstWaiting(source.awaiting_owner);
  if (source.artefacts && typeof source.artefacts === 'object') return firstWaiting(source.artefacts.awaiting_owner);
  if (Array.isArray(source.stages)) {
    for (const stage of source.stages) {
      const id = stage && stage.artefacts ? firstWaiting(stage.artefacts.awaiting_owner) : null;
      if (id) return id;
    }
  }
  return null;
}
