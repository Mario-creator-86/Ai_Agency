/**
 * THE ICONS JAVASCRIPT DRAWS.
 *
 * One family, one grid, one stroke. The seven room icons and the page's other
 * icons are written inline in index.html on exactly this grid; these four are
 * here because a script puts them on the page after it loads. Nothing in this
 * file states a colour or a size: `.ui-icon` in style.css carries the stroke
 * width, the caps and joins, the measure, and `stroke: currentColor`, so an
 * icon always takes the ink of the control it sits in.
 *
 * Every path is drawn inside 4..20 of the 24 grid, which is what makes seven
 * different shapes carry the same optical weight at the 15px they are drawn at.
 */

/** @type {Record<string, string>} */
const PATHS = {
  folder: '<path d="M4 7h6l2 2h8v10H4zM4 7V4.5h6l2 2.5h6"/>',
  wallet: '<path d="M4.5 7.5v11h15v-11zM4.5 7.5V5h13v2.5M15 11h4.5v4H15z"/><path d="M17 13h.1"/>',
  completed: '<circle cx="12" cy="12" r="8"/><path d="m8.3 12 2.4 2.6 5-5.2"/>',
  queue: '<rect x="4" y="4.5" width="3" height="3" rx=".5"/><rect x="4" y="10.5" width="3" height="3" rx=".5"/><rect x="4" y="16.5" width="3" height="3" rx=".5"/><path d="M10 6h10M10 12h10M10 18h7"/>',
  youtube: '<rect x="3.5" y="6" width="17" height="12" rx="3.5"/><path d="m10 9 5 3-5 3z"/>',
  shield: '<path d="m12 3.5 7 3v5c0 4.2-3 7.1-7 9-4-1.9-7-4.8-7-9v-5z"/><path d="m9 12 2 2 4-4"/>',
  activity: '<path d="M3.5 12h4l2.5-7 4 14 2.5-7h4"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3.5 2"/>',
  arrow: '<path d="M4.5 12h15M14 6.5l5.5 5.5-5.5 5.5"/>',
  refresh: '<path d="M19 10a7.5 7.5 0 1 0 .4 4M19 4.5V10h-5.5"/>',
  settings: '<path d="m9 4-.5 2-2 1-2-.5-1.5 3 1.5 1.5v2L3 14.5l1.5 3 2-.5 2 1 .5 2h4l.5-2 2-1 2 .5 1.5-3-1.5-1.5v-2l1.5-1.5-1.5-3-2 .5-2-1-.5-2z"/><circle cx="11" cy="12" r="3"/>',
  close: '<path d="M6.4 6.4l11.2 11.2M17.6 6.4L6.4 17.6"/>',
  expand: '<path d="M4.6 9.4V4.6h4.8M14.6 4.6h4.8v4.8M19.4 14.6v4.8h-4.8M9.4 19.4H4.6v-4.8"/>',
  collapse: '<path d="M9.2 4.4v4.8H4.4M14.8 4.4v4.8h4.8M19.6 14.8h-4.8v4.8M4.4 14.8h4.8v4.8"/>',
  play: '<path d="M7.6 5.6l10 6.4-10 6.4z"/>',
  // W36: the Owner's decisions and the price plates (Setări → Canale, Trezorerie → Prețurile modelelor)
  /** the Director's right: a seal with its check, the page's mark of an approval */
  seal: '<circle cx="12" cy="10.2" r="5.6"/><path d="M9.7 10.3l1.6 1.6 3-3.2M9.2 15.1L8 19.6l4-1.5 4 1.5-1.2-4.5"/>',
  /** the serial's channel: a clapperboard */
  clapper: '<path d="M4.8 10.4h14.4v8a1.2 1.2 0 0 1-1.2 1.2H6a1.2 1.2 0 0 1-1.2-1.2z"/><path d="M4.6 10.2l-.5-2.3 13.6-3.1.6 2.3zM8.3 9.3l1.4-3M12.5 8.4l1.4-3"/>',
  /** a channel of short factual films: a 9:16 frame */
  shortform: '<path d="M9 4.4h6a1.6 1.6 0 0 1 1.6 1.6v12a1.6 1.6 0 0 1-1.6 1.6H9A1.6 1.6 0 0 1 7.4 18V6A1.6 1.6 0 0 1 9 4.4zM10.6 16.8h2.8"/>',
  /** a provider's plate: the hexagon its first letter is set in */
  hexagon: '<path d="M12 4l6.9 4v8L12 20l-6.9-4V8z"/>',
};

/**
 * One icon of the family, as markup.
 * @param {keyof typeof PATHS | string} name
 * @returns {string}
 */
export function icon(name) {
  const paths = PATHS[name];
  if (!paths) return '';
  return `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
}
