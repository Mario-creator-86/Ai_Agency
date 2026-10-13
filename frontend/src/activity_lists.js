/** Chronological activity cards share ordering and preserve the reader's visible card. */
const CARD_SELECTOR = '[data-card-key], [data-message], [data-letter], .topic-card[data-id], .chat-item[data-id], .storyboard-card[data-id], .script-episode[data-id]';
const KEY_ATTRS = ['data-card-key', 'data-message', 'data-letter', 'data-id'];

/** @template T @param {T[]} rows @param {{oldestFirst?: boolean, time?: (row: T) => unknown}} [options] @returns {T[]} */
export function newestFirst(rows, options = {}) {
  const time = options.time || ((/** @type {any} */ row) => row.created_at || row.at || row.started_at || row.published_at || row.timestamp || row.fetched_at || row.requested_at);
  return (Array.isArray(rows) ? rows : []).map((row, index) => ({ row, index, at: Date.parse(String(time(row) || '')) }))
    .sort((a, b) => {
      if (Number.isFinite(a.at) && Number.isFinite(b.at) && a.at !== b.at) return b.at - a.at;
      if (Number.isFinite(a.at) !== Number.isFinite(b.at)) return Number.isFinite(a.at) ? -1 : 1;
      return options.oldestFirst ? b.index - a.index : a.index - b.index;
    }).map(({ row }) => row);
}

/** @param {Element} card */
function keyOf(card) {
  for (const name of KEY_ATTRS) {
    const value = card.getAttribute(name);
    if (value) return `${name}:${value}`;
  }
  return '';
}

/** @param {HTMLElement} host @returns {HTMLElement} */
function scrollContainer(host) {
  const doc = host.ownerDocument;
  for (let node = host; node; node = /** @type {HTMLElement} */ (node.parentElement)) {
    const style = doc?.defaultView?.getComputedStyle(node);
    if (style && /auto|scroll/.test(style.overflowY)) return node;
  }
  return /** @type {HTMLElement} */ (doc?.scrollingElement || host);
}

/** Capture immediately before a synchronous mutation, after any network request finishes.
 * @param {HTMLElement} host @returns {() => void} */
export function preserveReading(host) {
  if (!host.getBoundingClientRect || !host.querySelectorAll) return () => {};
  const scroller = scrollContainer(host);
  const top = scroller.scrollTop;
  const view = scroller === host.ownerDocument?.scrollingElement ? {top: 0, bottom: host.ownerDocument.defaultView?.innerHeight || scroller.clientHeight} : scroller.getBoundingClientRect();
  const hostBefore = host.getBoundingClientRect();
  const visible = Array.from(host.querySelectorAll(CARD_SELECTOR)).map((card) => ({ key: keyOf(card), rect: card.getBoundingClientRect() }))
    .filter(({ key, rect }) => key && rect.bottom > view.top && rect.top < view.bottom);
  // We restore by card identity, not by a raw scrollTop that now belongs to another card.
  const oldAnchor = scroller.style.overflowAnchor;
  scroller.style.overflowAnchor = 'none';
  return () => {
    if (top <= 2) scroller.scrollTop = 0;
    else {
      const cards = new Map(Array.from(host.querySelectorAll(CARD_SELECTOR)).map((card) => [keyOf(card), card]));
      const held = visible.find((item) => cards.has(item.key));
      if (held) {
        const card = cards.get(held.key);
        scroller.scrollTop += (card?.getBoundingClientRect().top || 0) - held.rect.top;
      } else if (hostBefore.bottom <= view.top) {
        scroller.scrollTop = top + host.getBoundingClientRect().height - hostBefore.height;
      } else scroller.scrollTop = top;
    }
    // Flush layout while native anchoring is disabled, so it cannot compensate a second time.
    scroller.getBoundingClientRect();
    scroller.style.overflowAnchor = oldAnchor;
  };
}

/** @param {HTMLElement} host @param {string} html */
export function replaceActivityHtml(host, html) {
  const restore = preserveReading(host);
  const expanded = new Map(Array.from(host.querySelectorAll?.('details') || []).map((node) => {
    const parent = node.closest(CARD_SELECTOR);
    return [parent ? keyOf(parent) + ':' + Array.from(parent.querySelectorAll('details')).indexOf(node) : node.id, node.open];
  }));
  host.innerHTML = html;
  for (const node of Array.from(host.querySelectorAll?.('details') || [])) {
    const parent = node.closest(CARD_SELECTOR);
    const key = parent ? keyOf(parent) + ':' + Array.from(parent.querySelectorAll('details')).indexOf(node) : node.id;
    if (expanded.has(key)) node.open = Boolean(expanded.get(key));
  }
  restore();
}
