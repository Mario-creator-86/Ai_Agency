/**
 * The section rail of a long dialog.
 *
 * Presentation only: the rail's links repeat headings that are already on the page, the
 * sections they point at are the ones the markup already had, and nothing here reads,
 * writes or reformats any of the studio's data. All it decides is which of the rail's
 * links is marked while the Owner reads down the report.
 */

/**
 * Which section a scroll position is reading.
 *
 * The rule is the one a reader would state: the current section is the last one whose
 * heading has already crossed the reading line a quarter of the way down the body — and
 * when the body is scrolled to its end, it is the last section, because a short final
 * section can never reach the line and would otherwise never be marked.
 *
 * @param {{ id: string, top: number }[]} sections  section tops, in body scroll coordinates
 * @param {number} scrollTop
 * @param {number} viewport      the visible height of the scrolling body
 * @param {number} scrollHeight  the full scrollable height of the body
 * @returns {string | null} the id of the section being read, or null if there are none
 */
export function currentSectionId(sections, scrollTop, viewport, scrollHeight) {
  if (!sections.length) return null;
  const ordered = [...sections].sort((a, b) => a.top - b.top);
  // A body with no height has not been shown yet: a closed dialog measures zero, and
  // answering "the last section" there would mark the wrong link before he ever scrolls.
  if (viewport <= 0) return ordered[0].id;
  // Scrolled to the bottom of a body that actually scrolls: whatever is last is what he is
  // looking at, however short it is. A body with nothing to scroll shows every section at
  // once, and then the honest answer is the first.
  if (scrollHeight > viewport && scrollTop + viewport >= scrollHeight - 2) {
    return ordered[ordered.length - 1].id;
  }
  const line = scrollTop + viewport * 0.25;
  let current = ordered[0].id;
  for (const section of ordered) {
    if (section.top <= line) current = section.id;
  }
  return current;
}

/**
 * Wire one rail to the body it navigates. Returns a teardown function.
 *
 * @param {HTMLElement | null} body the scrolling `.dialog-body`
 * @returns {() => void}
 */
export function attachRail(body) {
  const rail = body && body.querySelector('.dialog-rail');
  if (!body || !rail) return () => {};
  const links = /** @type {HTMLAnchorElement[]} */ (
    Array.prototype.slice.call(rail.querySelectorAll('a[href^="#"]'))
  );
  if (!links.length) return () => {};

  // offsetTop belongs to the nearest positioned ancestor, which may be the dialog or
  // a nested pane. Both navigation and the current marker need the body's coordinates.
  const topInBody = (/** @type {Element} */ target) =>
    target.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - body.clientTop;

  const targets = () =>
    links
      .map((link) => {
        const target = /** @type {HTMLElement | null} */ (
          body.querySelector(`#${CSS.escape(link.getAttribute('href').slice(1))}`)
        );
        return target ? { id: target.id, top: topInBody(target) } : null;
      })
      .filter(Boolean);

  const mark = () => {
    const id = currentSectionId(
      /** @type {{id: string, top: number}[]} */ (targets()),
      body.scrollTop,
      body.clientHeight,
      body.scrollHeight,
    );
    for (const link of links) {
      link.setAttribute('aria-current', link.getAttribute('href') === `#${id}` ? 'true' : 'false');
    }
  };

  // A rail link scrolls the body, never the page and never the address bar: a dialog has
  // no place in history, and letting the anchor fire would leave a fragment behind.
  const click = (/** @type {Event} */ event) => {
    const link = /** @type {HTMLElement} */ (event.target);
    if (!(link instanceof HTMLAnchorElement)) return;
    const target = body.querySelector(`#${CSS.escape(link.getAttribute('href').slice(1))}`);
    if (!target) return;
    event.preventDefault();
    // A scripted smooth scroll ignores the CSS that zeroes motion, so the preference is
    // read here too: someone who asked for no movement gets the jump, not the glide.
    const still =
      typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    // Native section navigation resolves skipped content-visibility layouts before
    // scrolling; a destination computed from placeholder heights can land in a gap.
    target.scrollIntoView({
      block: 'start',
      inline: 'nearest',
      behavior: still ? 'auto' : 'smooth',
    });
  };

  rail.addEventListener('click', click);
  body.addEventListener('scroll', mark, { passive: true });
  // The dialog is closed when this runs, so the body has no size and the sections have no
  // tops yet. It is also filled from the network after it opens. Both arrive as a resize
  // of the body, which is the one signal that covers opening and loading alike.
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(mark) : null;
  if (observer) {
    observer.observe(body);
    const pane = body.querySelector('.dialog-pane');
    if (pane) observer.observe(pane);
  }
  mark();
  return () => {
    rail.removeEventListener('click', click);
    body.removeEventListener('scroll', mark);
    if (observer) observer.disconnect();
  };
}
