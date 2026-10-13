import { escapeHtml } from './html.js';
import {
  DECISION_CARDS_PATH,
  answerCard,
  decisionsBadge,
  decisionsButtonLabel,
  needsConfirm,
  readDecisionFeed,
  refreshesOn,
  windowHtml,
} from './owner_decisions.js';

/**
 * «DECIZII» — HIS WINDOW (DECISIONS_WINDOW, 2026-10-03). The «Decizii» key in the top bar, with
 * the count of what waits for him, opens a full-height modal panel over the page: «Te așteaptă»
 * and «Istoric», one card per question (owner_decisions.js draws them and sends his answers).
 *
 * A modal <dialog>: the page behind is inert, so the keyboard stays inside; Esc closes it and the
 * focus goes back to the key that opened it. One persistent status line (role=status) outside the
 * part a repaint replaces, so each notice is heard as a change of one live region. A repaint gives
 * the focus back to the key that had it, and waits while he types in a note.
 *
 * It reads the feed when it opens, after each answer, on the events socket (a decision, an
 * approval, a letter or his policy moved) and on the page's own poll, at most every 30 s while
 * closed. Nothing is decided here: every answer is his press, sent to the route the card names.
 */

/** How often the closed window reads the count, at most (ms). */
const COUNT_EVERY_MS = 30000;
/** The socket's events come in bursts; the window reads once after the burst (ms). */
const EVENT_SETTLE_MS = 600;
/** After his note loses the focus, the repaint that waited for him runs (ms). */
const TYPING_SETTLE_MS = 250;

/**
 * @typedef {{
 *   api: (path: string, options?: any) => Promise<any>,
 *   button: HTMLButtonElement,
 *   badge: HTMLElement,
 *   openSettings: (tab: string) => void,
 *   openThread?: (threadId: string) => void,
 *   threadOf?: (letterId: string) => string|null,
 *   timezone?: () => string|undefined,
 *   onAnswered?: () => Promise<void>|void,
 *   fallbackCount?: () => number,
 * }} DecisionsDeps
 */

/** @param {Element|null} element @param {Element} body */
function focusKey(element, body) {
  if (!(element instanceof HTMLElement) || !body.contains(element)) return '';
  const attrs = Array.from(element.attributes).filter((a) => a.name.startsWith('data-') || (a.name === 'value' && element instanceof HTMLInputElement));
  if (!attrs.length) return '';
  return element.tagName.toLowerCase() + attrs.map((a) => (a.value ? `[${a.name}="${CSS.escape(a.value)}"]` : `[${a.name}]`)).join('');
}

/** @param {Element} body @param {string} key @param {HTMLElement|null} fallback */
function restoreFocus(body, key, fallback) {
  if (!key) return;
  const again = /** @type {HTMLElement|null} */ (body.querySelector(key));
  if (again && !(/** @type {HTMLButtonElement} */ (again).disabled)) again.focus({ preventScroll: true });
  else fallback?.focus({ preventScroll: true });
}

export class DecisionsWindow {
  /** @param {DecisionsDeps} deps */
  constructor(deps) {
    this.deps = deps;
    this.feed = readDecisionFeed(null);
    /** @type {'pending'|'ok'|'failed'|'missing'} */
    this.read = 'pending';
    this.error = '';
    /** @type {'waiting'|'history'} */
    this.tab = 'waiting';
    /** what he chose and wrote on each card, kept across repaints @type {Map<string, {option?: string|null, note?: string}>} */
    this.drafts = new Map();
    /** @type {string|null} the card whose confirmation line is open */
    this.confirming = null;
    /** @type {string|null} the card whose answer is in flight */
    this.busy = null;
    this.lastRead = 0;
    this.generation = 0;
    /** @type {Promise<void>|null} */
    this.reading = null;
    this.eventTimer = 0;
    this.typingTimer = 0;
    this.paintWaits = false;
    this.pressing = false;
    /** @type {HTMLElement|null} */
    this.opener = null;
    this.dialog = this.build();
    deps.button.addEventListener('click', () => { void this.open(); });
    this.paintButton();
  }

  /** The dialog, once: its header, its status line, and the body a repaint replaces. */
  build() {
    const dialog = document.createElement('dialog');
    dialog.id = 'decisions-window';
    dialog.className = 'studio-dialog decisions-window';
    dialog.setAttribute('aria-labelledby', 'decisions-title');
    dialog.innerHTML = '<div class="dialog-header decisions-header"><div>'
      + '<p class="eyebrow dialog-eyebrow">PROPRIETARUL · DOAR TU DECIZI</p>'
      + '<h2 class="dialog-title" id="decisions-title">Decizii</h2>'
      + '<p class="dialog-desc">Tot ce așteaptă răspunsul tău: pașii plătiți, recomandările angajaților și ale auditului, scrisorile care te întreabă ceva. Un angajat poate doar propune; nimic nu se aplică fără „Accept” al tău.</p></div>'
      + '<button type="button" class="dialog-close" data-decisions-close aria-label="Închide fereastra deciziilor">'
      + '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 6.4l11.2 11.2M17.6 6.4L6.4 17.6"/></svg></button></div>'
      + '<p class="decisions-status" role="status" aria-live="polite" data-decisions-status hidden></p>'
      + '<div class="decisions-body" data-decisions-body></div>';
    document.body.append(dialog);
    dialog.addEventListener('click', (event) => { void this.onClick(event); });
    dialog.addEventListener('keydown', (event) => this.onKey(event));
    dialog.addEventListener('input', (event) => this.onInput(event));
    dialog.addEventListener('change', (event) => this.onInput(event));
    dialog.addEventListener('pointerdown', () => { this.pressing = true; });
    dialog.addEventListener('pointerup', () => { this.pressing = false; this.settleTyping(); });
    dialog.addEventListener('pointercancel', () => { this.pressing = false; this.settleTyping(); });
    dialog.addEventListener('focusout', () => this.settleTyping());
    // Esc is the dialog's own cancel; the close returns the focus to the key that opened it
    dialog.addEventListener('close', () => {
      this.confirming = null;
      const back = this.opener && this.opener.isConnected ? this.opener : this.deps.button;
      this.opener = null;
      if (back && !back.hidden) back.focus({ preventScroll: true });
    });
    return dialog;
  }

  /** @returns {HTMLElement} */
  body() {
    return /** @type {HTMLElement} */ (this.dialog.querySelector('[data-decisions-body]'));
  }

  /** The window's one status line. @param {string} text @param {boolean} [alert] */
  status(text, alert = false) {
    const line = /** @type {HTMLElement|null} */ (this.dialog.querySelector('[data-decisions-status]'));
    if (!line) return;
    if (line.textContent !== text) line.textContent = text;
    line.dataset.tone = alert ? 'alert' : 'ok';
    line.hidden = !text;
  }

  /** What the key in the top bar says: the count, and his window's name for a screen reader. */
  count() {
    if (this.read === 'missing' && this.deps.fallbackCount) return this.deps.fallbackCount();
    return this.feed.count;
  }

  paintButton() {
    const n = this.count();
    const badge = decisionsBadge(n);
    this.deps.badge.textContent = badge;
    this.deps.badge.hidden = !badge;
    this.deps.button.setAttribute('aria-label', decisionsButtonLabel(n));
    this.deps.button.title = decisionsButtonLabel(n);
    this.deps.button.classList.toggle('has-waiting', n > 0);
  }

  /** Draws the open tab; waits while he types in a note, so his words and caret stay. */
  paint() {
    this.paintButton();
    if (!this.dialog.open) return;
    const body = this.body();
    const active = document.activeElement;
    if (active instanceof HTMLTextAreaElement && active.tagName === 'TEXTAREA' && body.contains(active)) {
      this.paintWaits = true;
      return;
    }
    this.paintWaits = false;
    const focused = focusKey(active, body);
    const threads = new Map();
    if (this.deps.threadOf) {
      for (const card of this.feed.cards) {
        if (card.source_type !== 'letter') continue;
        const thread = this.deps.threadOf(card.id);
        if (thread) threads.set(card.id, thread);
      }
    }
    body.innerHTML = windowHtml(this.feed, {
      escape: escapeHtml,
      timezone: this.deps.timezone ? this.deps.timezone() : undefined,
      tab: this.tab,
      read: this.read,
      error: this.error,
      busy: this.busy,
      confirming: this.confirming,
      drafts: this.drafts,
      threads,
    });
    restoreFocus(body, focused, /** @type {HTMLElement|null} */ (this.dialog.querySelector('[data-decisions-close]')));
  }

  /** A repaint that waited for his note runs once he has left it and is not pressing a key. */
  settleTyping() {
    if (!this.paintWaits) return;
    window.clearTimeout(this.typingTimer);
    this.typingTimer = window.setTimeout(() => {
      if (!this.pressing && this.paintWaits) this.paint();
    }, TYPING_SETTLE_MS);
  }

  /** Reads the feed (one read at a time), then draws. */
  load() {
    if (this.reading) return this.reading;
    const generation = this.generation;
    this.reading = (async () => {
      try {
        const payload = await this.deps.api(`${DECISION_CARDS_PATH}?history=true`);
        if (generation !== this.generation) return;
        this.feed = readDecisionFeed(payload);
        this.read = 'ok';
        this.error = '';
      } catch (error) {
        if (generation !== this.generation) return;
        const status = error && /** @type {any} */ (error).status;
        this.read = status === 404 ? 'missing' : 'failed';
        this.error = error instanceof Error ? error.message : '';
      } finally {
        if (generation === this.generation) this.lastRead = Date.now();
        this.reading = null;
      }
      if (generation === this.generation) this.paint();
    })();
    return this.reading;
  }

  /** The page's poll: the window reads when it is open, else at most every COUNT_EVERY_MS. @param {boolean} [force] */
  refreshCount(force = false) {
    if (this.deps.button.hidden && !force) return;
    if (force || this.dialog.open || Date.now() - this.lastRead >= COUNT_EVERY_MS) void this.load();
  }

  /** An event of the socket: the window reads again once the burst has passed. @param {any} event */
  onEvent(event) {
    if (this.deps.button.hidden || !refreshesOn(event)) return;
    window.clearTimeout(this.eventTimer);
    this.eventTimer = window.setTimeout(() => { void this.load(); }, EVENT_SETTLE_MS);
  }

  /** After his key was accepted: the key shows and the count is read. */
  signedIn() {
    this.deps.button.hidden = false;
    this.refreshCount(true);
  }

  /** He signed out: the window closes and forgets everything it read and he wrote. */
  reset() {
    this.generation += 1;
    window.clearTimeout(this.eventTimer);
    window.clearTimeout(this.typingTimer);
    this.feed = readDecisionFeed(null);
    this.read = 'pending';
    this.error = '';
    this.tab = 'waiting';
    this.drafts.clear();
    this.confirming = null;
    this.busy = null;
    this.lastRead = 0;
    this.reading = null;
    this.paintWaits = false;
    this.status('');
    this.opener = null;
    if (this.dialog.open) this.dialog.close();
    this.body().replaceChildren();
    this.deps.button.hidden = true;
    this.paintButton();
  }

  /** Opens his window, at a tab when one is named. @param {'waiting'|'history'} [tab] */
  async open(tab) {
    if (tab) this.tab = tab;
    if (!this.dialog.open) {
      const active = document.activeElement;
      this.opener = active instanceof HTMLElement && active !== document.body ? active : this.deps.button;
      this.dialog.showModal();
    }
    this.paint();
    // the first key of the window takes the focus, never the page behind it
    const first = /** @type {HTMLElement|null} */ (this.dialog.querySelector(`[data-decisions-tab="${this.tab}"]`));
    first?.focus({ preventScroll: true });
    await this.load();
  }

  /** @param {string} cardId */
  card(cardId) {
    return this.feed.cards.find((card) => card.card_id === cardId) || null;
  }

  /** @param {string} cardId */
  draft(cardId) {
    let draft = this.drafts.get(cardId);
    if (!draft) {
      draft = {};
      this.drafts.set(cardId, draft);
    }
    return draft;
  }

  /** His choice of option and his note, kept as he makes them. @param {Event} event */
  onInput(event) {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const cardId = target.dataset.card || '';
    if (!cardId) return;
    if (target instanceof HTMLTextAreaElement && target.hasAttribute('data-decision-note')) this.draft(cardId).note = target.value;
    if (target instanceof HTMLInputElement && target.hasAttribute('data-decision-option') && target.checked) this.draft(cardId).option = target.value;
  }

  /** Arrow keys walk the two tabs (WAI-ARIA tabs). @param {KeyboardEvent} event */
  onKey(event) {
    const target = event.target;
    if (!(target instanceof HTMLElement) || !target.hasAttribute('data-decisions-tab')) return;
    const order = /** @type {('waiting'|'history')[]} */ (['waiting', 'history']);
    const at = order.indexOf(/** @type {'waiting'|'history'} */ (target.dataset.decisionsTab));
    let next = -1;
    if (event.key === 'ArrowRight') next = (at + 1) % order.length;
    else if (event.key === 'ArrowLeft') next = (at + order.length - 1) % order.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = order.length - 1;
    if (next < 0) return;
    event.preventDefault();
    this.showTab(order[next]);
  }

  /** @param {'waiting'|'history'} tab */
  showTab(tab) {
    this.tab = tab;
    this.confirming = null;
    this.paint();
    /** @type {HTMLElement|null} */ (this.dialog.querySelector(`[data-decisions-tab="${tab}"]`))?.focus({ preventScroll: true });
  }

  /** @param {Event} event */
  async onClick(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if (target.closest('[data-decisions-close]')) {
      this.dialog.close();
      return;
    }
    const tab = target.closest('[data-decisions-tab]');
    if (tab) {
      this.showTab(/** @type {'waiting'|'history'} */ (tab.getAttribute('data-decisions-tab') === 'history' ? 'history' : 'waiting'));
      return;
    }
    const keyNode = /** @type {HTMLButtonElement|null} */ (target.closest('[data-decision-action]'));
    if (!keyNode || keyNode.disabled) return;
    const action = keyNode.dataset.decisionAction || '';
    const cardId = keyNode.dataset.card || '';
    if (action === 'place') {
      this.deps.openSettings(keyNode.dataset.decisionPlace || 'llm');
      return;
    }
    if (action === 'thread') {
      if (this.deps.openThread && keyNode.dataset.decisionThread) this.deps.openThread(keyNode.dataset.decisionThread);
      return;
    }
    const card = this.card(cardId);
    if (!card || this.busy) return;
    const draft = this.draft(cardId);
    const optionKey = draft.option || card.recommended_option || (card.options[0] ? card.options[0].key : null);
    const option = card.options.find((o) => o.key === optionKey) || null;
    if (action === 'accept' && needsConfirm(card, option)) {
      this.confirming = cardId;
      this.paintWaits = false;
      this.paint();
      /** @type {HTMLElement|null} */ (this.body().querySelector(`[data-decision-action="confirm"][data-card="${CSS.escape(cardId)}"]`))?.focus({ preventScroll: true });
      return;
    }
    if (action === 'cancel') {
      this.confirming = null;
      this.paint();
      /** @type {HTMLElement|null} */ (this.body().querySelector(`[data-decision-action="accept"][data-card="${CSS.escape(cardId)}"]`))?.focus({ preventScroll: true });
      return;
    }
    /** @type {Record<string, 'ACCEPT'|'REFUSE'|'DONE'|'REPLY'|'RESOLVE'>} */
    const decisions = { accept: 'ACCEPT', confirm: 'ACCEPT', refuse: 'REFUSE', done: 'DONE', reply: 'REPLY', resolve: 'RESOLVE' };
    const decision = decisions[action];
    if (!decision) return;
    await this.send(card, decision, card.source_type === 'decision' ? optionKey : null, draft.note || '');
  }

  /**
   * His answer, sent once; the window says what happened and reads again.
   * @param {import('./owner_decisions.js').DecisionCard} card
   * @param {'ACCEPT'|'REFUSE'|'DONE'|'REPLY'|'RESOLVE'} decision
   * @param {string|null} optionKey
   * @param {string} note
   */
  async send(card, decision, optionKey, note) {
    const generation = this.generation;
    this.busy = card.card_id;
    this.confirming = null;
    this.paintWaits = false;
    this.status('Se trimite răspunsul tău…');
    this.paint();
    const result = await answerCard(this.deps.api, card, { decision, optionKey, note, commandId: crypto.randomUUID() });
    if (generation !== this.generation) return;
    this.busy = null;
    const ok = result.status === 'DONE' || result.status === 'WAITING';
    if (ok) this.drafts.delete(card.card_id);
    this.status(result.message, !ok && result.status !== 'SHEET');
    if (result.reload) await this.load();
    else this.paint();
    if (generation !== this.generation) return;
    // a guided accept opens the place where he carries it out; the card waits for him
    if (result.place) this.deps.openSettings(result.place);
    if (ok && this.deps.onAnswered) await this.deps.onAnswered();
  }
}
