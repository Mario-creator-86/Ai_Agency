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
  close: '<path d="M6.4 6.4l11.2 11.2M17.6 6.4L6.4 17.6"/>',
  expand: '<path d="M4.6 9.4V4.6h4.8M14.6 4.6h4.8v4.8M19.4 14.6v4.8h-4.8M9.4 19.4H4.6v-4.8"/>',
  collapse: '<path d="M9.2 4.4v4.8H4.4M14.8 4.4v4.8h4.8M19.6 14.8h-4.8v4.8M4.4 14.8h4.8v4.8"/>',
  play: '<path d="M7.6 5.6l10 6.4-10 6.4z"/>',
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
