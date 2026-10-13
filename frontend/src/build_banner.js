/**
 * THE PAGE'S OWN WARNINGS (PAGE_OWNER_DAY: PAGE-01, REL-07).
 *
 * Two things the Owner must see on every screen, both read from the snapshot:
 * - the page is older than the studio's sources (`page_build.stale`, backend app/page_build.py):
 *   on 2026-10-01 the studio served a bundle from 2026-09-27 that had no shooting sheet, and the
 *   render button answered 409 «Folosește foaia de filmare» to a page with nothing to open;
 * - something that keeps the studio running is wrong (`operations`, backend app/operations.py):
 *   the worker has not passed, the media disk is low, FFmpeg is missing, the backup is old. The
 *   sentence is the backend's own (`banner_ro`); the page only counts the problems after it.
 *
 * Pure, so what the banners say is tested; main.js paints them.
 */

/** The page's sentence when its bundle is older than the sources on disk. */
export const PAGE_STALE_WORDS = 'Pagina e mai veche decât studioul: repornește studioul.';

/**
 * «(încă o problemă)», «(încă 2 probleme)», «(încă 20 de probleme)».
 * @param {number} n
 */
function moreProblems(n) {
  if (n <= 0) return '';
  if (n === 1) return ' (încă o problemă)';
  const rest = n % 100;
  return ` (încă ${n}${n >= 20 && (rest === 0 || rest >= 20) ? ' de' : ''} probleme)`;
}

/**
 * @typedef {{kind: 'operations'|'page', text: string, tone: 'warn'|'alert'}} PageBanner
 */

/**
 * The banners that stand now: the studio's problem first, then the page's.
 * @param {any} snapshot GET /snapshot
 * @returns {PageBanner[]}
 */
export function pageBanners(snapshot) {
  /** @type {PageBanner[]} */
  const banners = [];
  const ops = snapshot && typeof snapshot === 'object' ? snapshot.operations : null;
  if (ops && typeof ops === 'object' && ops.status && ops.status !== 'HEALTHY') {
    const problems = Array.isArray(ops.problems) ? ops.problems : [];
    const first = String(ops.banner_ro || (problems[0] && problems[0].reason_ro) || '').trim();
    if (first) banners.push({ kind: 'operations', text: `${first}${moreProblems(problems.length - 1)}`, tone: 'alert' });
  }
  const build = snapshot && typeof snapshot === 'object' ? snapshot.page_build : null;
  if (build && typeof build === 'object' && build.stale === true) {
    banners.push({ kind: 'page', text: PAGE_STALE_WORDS, tone: 'warn' });
  }
  return banners;
}

/**
 * What the banners say, as one key: the page repaints only when it changes.
 * @param {PageBanner[]} banners
 */
export function bannersKey(banners) {
  return banners.map((b) => `${b.kind}|${b.tone}|${b.text}`).join('#');
}
