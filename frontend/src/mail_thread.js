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
  REQUEST_INFO: 'Question',
  REQUEST_REVIEW: 'Review request',
  CHALLENGE: 'Challenge',
  HANDOFF: 'Handoff / guidance',
  STATUS: 'Report',
  ESCALATE: 'Escalation',
};

const STATUS_LABEL = {
  OPEN: 'open',
  ANSWERED: 'answered',
  RESOLVED: 'resolved',
};

/**
 * @param {string|undefined} iso
 * @param {string|undefined} timezone
 */
function when(iso, timezone) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('ro-RO', {
      dateStyle: 'medium',
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
    return '<div class="helper">The thread is empty: no message recorded.</div>';
  }
  return messages
    .map((m, index) => {
      const from = m.from_name || 'Owner';
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
          ? `<div class="mail-footer">${escape(STATUS_LABEL[m.status] || m.status)}${m.resolved_by ? ` by ${escape(m.resolved_by)}` : ''}${m.resolution && m.resolution !== full ? ` — ${escape(m.resolution)}` : ''}</div>`
          : '';
      const forOwner = Boolean(m.for_owner) || to === 'Owner';
      return (
        `<article class="mail-letter${index === 0 ? ' is-first' : ''}${forOwner ? ' is-owner' : ''}" data-message="${escape(m.id)}">` +
        (forOwner && m.status === 'OPEN' ? '<div class="mail-owner-flag">To you — awaiting your reply</div>' : '') +
        `<div class="mail-meta"><span class="mail-route"><strong>${escape(from)}</strong> <span class="mail-arrow">→</span> <strong>${escape(to)}</strong></span>` +
        `<time>${escape(when(m.created_at, timezone))}</time></div>` +
        `<div class="mail-subject"><span class="policy-tag policy-locked">${escape(INTENT_LABEL[m.intent] || m.intent)}</span>${subjectEchoesTitle ? '' : ` ${escape(m.subject)}`}</div>` +
        // A letter with no text at all says so; a letter whose text is already the end
        // of its own subject simply does not print it a second time.
        (text
          ? `<div class="mail-body">${escape(text)}</div>`
          : full
            ? ''
            : '<div class="mail-body mail-empty">(no text; subject only)</div>') +
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
   *          api: (path: string, options?: any) => Promise<any>, escape: (s: any) => string}} parts
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
    this.body.innerHTML = '<div class="helper">Loading the thread…</div>';
    this.status.textContent = '';
    this.status.hidden = true;
    if (!this.dialog.open) this.dialog.showModal();
    await this.load(threadId);
  }

  async load(threadId) {
    try {
      this.thread = await this.api(`/agents/messages/threads/${encodeURIComponent(threadId)}`);
      const count = this.thread.messages.length;
      this.title.textContent = this.thread.subject || 'Correspondence thread';
      this.body.innerHTML = renderThread(this.thread, {
        escape: this.escape,
        timezone: this.timezone,
      });
      this.body.dataset.count = String(count);
      this.body.scrollTop = this.body.scrollHeight;
    } catch (error) {
      this.body.innerHTML = `<div class="text-error">${this.escape(error instanceof Error ? error.message : 'The thread could not be read.')}</div>`;
    }
  }

  /** The Owner's reply goes to whoever wrote last, into the same thread. */
  async reply() {
    const text = this.input.value.trim();
    if (!text || !this.thread || !this.thread.messages.length) return;
    const last = this.thread.messages[this.thread.messages.length - 1];
    this.status.hidden = false;
    this.status.textContent = 'Sending…';
    try {
      await this.api(`/agents/messages/${encodeURIComponent(last.id)}/reply`, {
        method: 'POST',
        body: JSON.stringify({ text }),
      });
      this.input.value = '';
      this.status.textContent = 'Sent. The employee answers on the next pass of the worker.';
      await this.load(this.thread.thread_id);
    } catch (error) {
      this.status.textContent = error instanceof Error ? error.message : 'Could not send.';
    }
  }
}
