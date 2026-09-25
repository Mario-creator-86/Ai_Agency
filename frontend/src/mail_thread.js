/**
 * A thread of letters, read as mail.
 *
 * The ledger shows that a letter was sent; this window shows the exchange it belongs to —
 * who wrote to whom, when, about what, the letter itself and how it ends — oldest first, so a
 * forwarded thread reads the way it was lived. The Owner can write back from the bottom of
 * the window; the reply goes to whoever wrote last, into the same thread.
 *
 * `renderThread` is pure so what the window says is testable.
 */

const INTENT_LABEL = {
  REQUEST_INFO: 'Întrebare',
  REQUEST_REVIEW: 'Cerere de verificare',
  CHALLENGE: 'Obiecție',
  HANDOFF: 'Îndrumare',
  STATUS: 'Raport',
  ESCALATE: 'Escaladare',
};

const STATUS_LABEL = {
  OPEN: 'deschis',
  ANSWERED: 'răspuns',
  RESOLVED: 'rezolvat',
};

/**
 * @param {string|undefined} iso
 * @param {string|undefined} timezone
 */
export function when(iso, timezone) {
  if (!iso) return '';
  try {
    // W28: the page's date style, «12.09.2026, 10:37» (the chat's and the dialogs'), not «12 sept. 2026»
    return new Date(iso).toLocaleString('ro-RO', {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: timezone,
    });
  } catch {
    return String(iso).slice(0, 16).replace('T', ' ');
  }
}

/**
 * The letter's text. A message written before letters existed carries only a structured
 * body; the parts of it a reader can use are shown as lines, never as raw JSON.
 * @param {any} message
 */
function letterText(message) {
  const text = String(message.body_text || '').trim();
  if (text) return text;
  const body = message.body_json && typeof message.body_json === 'object' ? message.body_json : {};
  const lines = [];
  for (const key of ['reason', 'note', 'instructions', 'detail', 'needs', 'summary']) {
    const value = body[key];
    if (typeof value === 'string' && value.trim()) lines.push(value.trim());
  }
  return lines.join('\n');
}

/**
 * The letter's body, when it is not already the end of its own subject.
 *
 * A report's subject is "selection: COMPLETED — <the sentence>" and its body is
 * <the sentence>, so the window printed it as the title, as the subject and as the
 * body. Nothing is reworded: the third copy is not drawn.
 *
 * @param {string|undefined} subject @param {string} text
 */
function bodyBeyondSubject(subject, text) {
  const tail = String(text || '').trim();
  if (!tail) return '';
  const head = String(subject || '').trim().toLowerCase();
  const b = tail.toLowerCase();
  return head && (head === b || head.endsWith(b)) ? '' : tail;
}

/**
 * @param {{thread_id: string, subject: string, messages: any[]}} thread
 * @param {{escape: (s: any) => string, timezone?: string}} options
 * @returns {string}
 */
export function renderThread(thread, { escape, timezone }) {
  const messages = Array.isArray(thread.messages) ? thread.messages : [];
  if (!messages.length) {
    return '<div class="helper">Firul este gol: niciun mesaj înregistrat.</div>';
  }
  return messages
    .map((m, index) => {
      const from = m.from_name || 'Proprietar';
      const to = m.to_name || 'Director';
      const full = letterText(m);
      const text = bodyBeyondSubject(m.subject, full);
      // The window's title is the thread's subject, so a letter whose subject is that
      // same sentence would print it again 150px below it (measured 2026-09-23: the
      // sentence appeared twice in one window). The intent tag still says what kind of
      // letter it is; only the repeated sentence is dropped.
      const subjectEchoesTitle =
        String(m.subject || '').trim().toLowerCase() === String(thread.subject || '').trim().toLowerCase();
      const footer =
        m.status && m.status !== 'OPEN'
          ? `<div class="mail-footer">${escape(STATUS_LABEL[m.status] || m.status)}${m.resolved_by ? ` de ${escape(m.resolved_by)}` : ''}${m.resolution && m.resolution !== full ? ` — ${escape(m.resolution)}` : ''}</div>`
          : '';
      const forOwner = Boolean(m.for_owner) || to === 'Owner';
      return (
        `<article class="mail-letter${index === 0 ? ' is-first' : ''}${forOwner ? ' is-owner' : ''}" data-message="${escape(m.id)}">` +
        (forOwner && m.status === 'OPEN' ? '<div class="mail-owner-flag">Pentru tine — așteaptă răspunsul tău</div>' : '') +
        `<div class="mail-meta"><span class="mail-route"><strong>${escape(from)}</strong> <span class="mail-arrow">→</span> <strong>${escape(to)}</strong></span>` +
        `<time>${escape(when(m.created_at, timezone))}</time></div>` +
        `<div class="mail-subject"><span class="policy-tag policy-locked">${escape(INTENT_LABEL[m.intent] || m.intent)}</span>${subjectEchoesTitle ? '' : ` ${escape(m.subject)}`}</div>` +
        // A letter with no text at all says so; a letter whose text is already the end
        // of its own subject simply does not print it a second time.
        (text
          ? `<div class="mail-body">${escape(text)}</div>`
          : full
            ? ''
            : '<div class="mail-body mail-empty">(fără text; doar subiectul)</div>') +
        footer +
        '</article>'
      );
    })
    .join('');
}

export class MailThread {
  /**
   * @param {{dialog: HTMLDialogElement, title: HTMLElement, body: HTMLElement,
   *          form: HTMLFormElement, input: HTMLTextAreaElement, status: HTMLElement,
   *          api: (path: string, options?: any) => Promise<any>, escape: (s: any) => string,
   *          landed?: () => Promise<void>}} parts
   */
  constructor(parts) {
    this.dialog = parts.dialog;
    this.title = parts.title;
    this.body = parts.body;
    this.form = parts.form;
    this.input = parts.input;
    this.status = parts.status;
    this.api = parts.api;
    this.escape = parts.escape;
    /** W30: resolves once the window's pane has landed; the letters are laid out then. */
    this.landed = parts.landed || (() => Promise.resolve());
    this.timezone = undefined;
    /** @type {{thread_id: string, subject: string, messages: any[]}|null} */
    this.thread = null;
    this.form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.reply();
    });
  }

  /** Open the window on one thread; the letters are fetched fresh every time. */
  async open(threadId) {
    if (!threadId) return;
    this.body.innerHTML = '<div class="helper">Se încarcă firul…</div>';
    this.status.textContent = '';
    this.status.hidden = true;
    if (!this.dialog.open) this.dialog.showModal();
    await this.load(threadId, true);
  }

  /** @param {string} threadId @param {boolean} [opening] the window is opening: lay out once it has landed */
  async load(threadId, opening = false) {
    try {
      this.thread = await this.api(`/agents/messages/threads/${encodeURIComponent(threadId)}`);
      // the heading at once (a line); the letters once the pane has landed
      this.title.textContent = this.thread.subject || 'Fir de corespondență';
      if (opening) await this.landed();
      if (!this.thread) return;
      const count = this.thread.messages.length;
      this.body.innerHTML = renderThread(this.thread, {
        escape: this.escape,
        timezone: this.timezone,
      });
      this.body.dataset.count = String(count);
      this.body.scrollTop = this.body.scrollHeight;
    } catch (error) {
      this.body.innerHTML = `<div class="text-error">${this.escape(error instanceof Error ? error.message : 'Firul nu a putut fi citit.')}</div>`;
    }
  }

  /** The Owner's reply goes to whoever wrote last, into the same thread. */
  async reply() {
    const text = this.input.value.trim();
    if (!text || !this.thread || !this.thread.messages.length) return;
    const last = this.thread.messages[this.thread.messages.length - 1];
    this.status.hidden = false;
    this.status.textContent = 'Se trimite…';
    try {
      await this.api(`/agents/messages/${encodeURIComponent(last.id)}/reply`, {
        method: 'POST',
        body: JSON.stringify({ text }),
      });
      this.input.value = '';
      this.status.textContent = 'Trimis. Angajatul răspunde la următoarea trecere a lucrătorului.';
      await this.load(this.thread.thread_id);
    } catch (error) {
      this.status.textContent = error instanceof Error ? error.message : 'Nu s-a putut trimite.';
    }
  }
}
