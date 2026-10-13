/**
 * What a speech bubble shows at a given moment.
 *
 * The bubble is a fixed size — three short lines over a character's head — and an agent's
 * answer is often much longer than that. It used to be cut at the first three lines, so the
 * Owner read the beginning of a verdict and never the verdict. The bubble now keeps its size
 * and shows the whole answer over time: the text is wrapped into pages of three lines, each
 * page types out at a readable speed, holds long enough to be read, then gives way to the
 * next. A page counter says how much is left, so a long answer looks long rather than lost.
 *
 * Both functions are pure, so the reading pace is testable without a canvas.
 */

/** Characters per line and lines per page: the bubble's shape, not a preference. */
export const LINE_CHARS = 24;
export const PAGE_LINES = 3;

/** How fast a page types, and how long a full page is held before the next one. */
export const CHARS_PER_SECOND = 26;
export const HOLD_SECONDS = 1.9;
/** A page nobody could read in this long is not worth showing; the chat has the full text. */
export const MAX_PAGES = 12;

/**
 * Wrap text into pages of `PAGE_LINES` lines of at most `LINE_CHARS` characters.
 *
 * A word longer than a line (a URL, an identifier) is split rather than dropped: the Owner
 * needs to see that it is there even if it takes two lines.
 *
 * @param {string} text
 * @param {number} [lineChars]
 * @param {number} [pageLines]
 * @returns {string[][]} pages, each an array of lines
 */
export function bubblePages(text, lineChars = LINE_CHARS, pageLines = PAGE_LINES) {
  const words = String(text ?? '').toUpperCase().split(/\s+/).filter(Boolean);
  /** @type {string[]} */
  const lines = [];
  let line = '';
  const push = () => {
    if (line) lines.push(line);
    line = '';
  };
  for (let word of words) {
    while (word.length > lineChars) {
      push();
      lines.push(word.slice(0, lineChars));
      word = word.slice(lineChars);
    }
    if (!line) {
      line = word;
    } else if (line.length + 1 + word.length <= lineChars) {
      line = `${line} ${word}`;
    } else {
      push();
      line = word;
    }
  }
  push();
  /** @type {string[][]} */
  const pages = [];
  for (let i = 0; i < lines.length; i += pageLines) pages.push(lines.slice(i, i + pageLines));
  return pages.slice(0, MAX_PAGES);
}

/**
 * The frame to draw: which page, how much of it has been typed, and whether it is the last.
 *
 * @param {string[][]} pages
 * @param {number} elapsedSeconds since the bubble appeared
 * @returns {{lines: string[], pageIndex: number, pageCount: number, done: boolean}}
 */
export function bubbleFrame(pages, elapsedSeconds) {
  const pageCount = pages.length;
  if (!pageCount) return { lines: [], pageIndex: 0, pageCount: 0, done: true };
  let remaining = Math.max(0, elapsedSeconds);
  for (let index = 0; index < pageCount; index += 1) {
    const page = pages[index];
    const characters = page.join(' ').length;
    const typing = characters / CHARS_PER_SECOND;
    const total = typing + HOLD_SECONDS;
    const last = index === pageCount - 1;
    if (remaining < total || last) {
      const shown = Math.min(characters, Math.floor(Math.max(0, remaining) * CHARS_PER_SECOND));
      return {
        lines: typeInto(page, last && remaining >= typing ? characters : shown),
        pageIndex: index,
        pageCount,
        done: last && remaining >= total,
      };
    }
    remaining -= total;
  }
  return { lines: pages[pageCount - 1], pageIndex: pageCount - 1, pageCount, done: true };
}

/** The first `count` characters of a page, keeping the line breaks the wrap decided. */
function typeInto(page, count) {
  let left = count;
  /** @type {string[]} */
  const out = [];
  for (const line of page) {
    if (left <= 0) break;
    out.push(line.length <= left ? line : line.slice(0, left));
    // The space that ends a line counts as a character, so the pace matches the text length.
    left -= line.length + 1;
  }
  return out;
}

/**
 * How long the bubble must stay up for the whole answer to be readable.
 *
 * @param {string[][]} pages
 * @returns {number} milliseconds
 */
export function bubbleDurationMs(pages) {
  const seconds = pages.reduce(
    (total, page) => total + page.join(' ').length / CHARS_PER_SECOND + HOLD_SECONDS,
    0,
  );
  return Math.round(Math.max(4, seconds) * 1000);
}
