/**
 * A separate window that shows, in real time, what one employee is doing.
 *
 * The Owner asked to see an employee at work without opening the detail drawer: a button
 * opens a small standalone window that streams the employee's own events — starting to
 * think, what it says, what it finishes — as they happen. The window is fed by the main
 * page's event flow (the socket and the events endpoint both land in the ledger, and every
 * newly recorded event is forwarded here), seeded with the employee's day so opening it
 * shows context, not just "from now on". The inspector stays the place for the full detail
 * of each action; this window is the live view.
 *
 * The popup is a same-origin document the opener writes into. The page CSP forbids inline
 * scripts and inline styles, and a local-scheme document inherits that CSP, so the popup is
 * built entirely through the DOM and styled through a constructable stylesheet (CSSOM),
 * with the same palette tokens the application uses. A watchdog in the opener closes the
 * popup if the main page goes away; a popup that outlives the opener can only be closed by
 * hand, which is the honest worst case.
 */

import { describeEvent } from './ledger.js';

/**
 * Whether an event belongs to this employee.
 *
 * Agent-family events carry the agent as the aggregate; runs and messages carry it in the
 * payload. Production events (a claim extracted, a video rendered) do not name an employee
 * and are deliberately not matched: this window shows the person's own actions.
 *
 * @param {{event_type?: string, aggregate_id?: string, payload?: any}} event
 * @param {string} agentId
 * @returns {boolean}
 */
export function eventMatchesAgent(event, agentId) {
  if (!event || !agentId) return false;
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  if (payload.agent_id === agentId) return true;
  const type = String(event.event_type || '');
  if (type.split('.')[0] === 'agent' && event.aggregate_id === agentId) return true;
  if (type.startsWith('agent.message')) {
    return payload.from_agent_id === agentId || payload.to_agent_id === agentId;
  }
  return false;
}

/** The sentence under the header: what the employee is doing right now. */
export function nowLine(runtimeState, taskType) {
  if (runtimeState === 'THINKING' || runtimeState === 'WORKING') {
    return taskType ? `lucrează la sarcina ${String(taskType).replace(/_/g, ' ')}` : 'lucrează';
  }
  if (runtimeState === 'PAUSED') return 'pus pe pauză';
  return 'fără sarcină acum';
}

/** The popup's stylesheet, through CSSOM because the CSP forbids an inline <style>. */
const LIVE_STYLES = `
:root {
  --bg: #f5f4ef; --surface: #fffefa; --surface-sunk: #f2f2ea; --surface-quiet: #eef0e6;
  --line: #dfe3d9; --line-strong: #c9d1c2;
  --ink: #233b37; --ink-2: #5d6a62; --ink-3: #5f6a5d;
  --forest: #254e43; --forest-lift: #326753; --teal: #218371;
  --ok-bg: #e6ede4; --ok-line: #b4c9b8; --ok-ink: #3f6b52;
  --warn-bg: #f4eedd; --warn-line: #ddcba0; --warn-ink: #7f6329;
  --alert-bg: #f5eae3; --alert-line: #e6c3b0; --alert-ink: #9a573c;
  --info-bg: #e4efea; --info-line: #b3cfc4; --info-ink: #1f6b5c;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 13px/1.5 "Segoe UI", Arial, sans-serif; }
header { position: sticky; top: 0; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 14px 16px; background: var(--forest); color: #fff; }
header h1 { margin: 0; font-size: 15px; font-weight: 600; letter-spacing: -.2px; }
.pill { font-size: 10px; font-weight: 700; letter-spacing: .08em; padding: 4px 10px; border-radius: 20px; background: var(--surface-quiet); color: var(--ink-2); border: 1px solid var(--line-strong); white-space: nowrap; }
.pill.is-busy { background: var(--warn-bg); color: var(--warn-ink); border-color: var(--warn-line); }
.now { margin: 0; padding: 10px 16px; font-size: 12.5px; color: var(--ink-2); border-bottom: 1px solid var(--line); background: var(--surface); }
.now strong { color: var(--ink); }
.live-feed { list-style: none; margin: 0; padding: 6px 16px 16px; display: flex; flex-direction: column; gap: 6px; }
.live-row { display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 8px; padding: 7px 8px; background: var(--surface); border: 1px solid var(--line); border-left: 3px solid var(--line-strong); border-radius: 6px; }
.live-row time { font-size: 10.5px; color: var(--ink-3); padding-top: 2px; font-variant-numeric: tabular-nums; }
.live-head { color: var(--ink); }
.live-head strong { font-weight: 650; }
.live-text { color: var(--ink-2); margin-top: 2px; overflow-wrap: anywhere; white-space: pre-wrap; }
.live-speech { border-left-color: var(--forest); }
.live-production { border-left-color: #4a7fb5; }
.live-money { border-left-color: var(--warn-ink); }
.live-owner { border-left-color: var(--alert-ink); }
.live-empty { padding: 18px 16px; color: var(--ink-3); font-style: italic; }
footer { position: fixed; bottom: 0; left: 0; right: 0; padding: 8px 16px; font-size: 10.5px; color: var(--ink-3); background: var(--surface); border-top: 1px solid var(--line); }
`;

export class LiveWindows {
  /**
   * @param {{escape?: (s: string) => string, names?: Record<string, string>, timezone?: string}} tools
   */
  constructor(tools = {}) {
    this.names = tools.names || {};
    this.timezone = tools.timezone;
    /** @type {Map<string, {win: Window, pill: HTMLElement, now: HTMLElement, feed: HTMLElement, seen: Set<string>}>} */
    this.entries = new Map();
    setInterval(() => this._watchdog(), 4000);
  }

  setNames(names) {
    this.names = names || {};
  }

  /**
   * Open (or focus) the live window of one employee.
   *
   * @param {{id?: string, agent_id?: string, display_name?: string, role_name?: string, runtime_state?: string}} agent
   * @param {{events?: any[], runtimeState?: string, timezone?: string}} [options]
   * @returns {boolean} false when the browser blocked the popup
   */
  open(agent, options = {}) {
    const id = agent.id || agent.agent_id;
    if (!id) return false;
    const existing = this.entries.get(id);
    if (existing && !existing.win.closed) {
      existing.win.focus();
      return true;
    }
    const win = window.open('', `studio-live-${id}`, 'popup=yes,width=580,height=780');
    if (!win) return false;
    const entry = this._build(win, agent, options.runtimeState || agent.runtime_state || 'IDLE');
    this.entries.set(id, entry);
    if (options.timezone) this.timezone = options.timezone;
    // Seed with the employee's day so the window opens with context. The feed shows newest
    // first and new rows are inserted at the top, so the seed — newest first from the
    // ledger — is applied oldest-first to end with the newest on top.
    const seed = (options.events || []).filter((e) => eventMatchesAgent(e, id)).slice(0, 120).reverse();
    for (const event of seed) {
      this._addEvent(id, event);
    }
    this._refreshEmpty(entry);
    return true;
  }

  /** Forward one newly recorded event; only the windows it belongs to hear about it. */
  broadcast(event) {
    if (!event || !event.event_id) return;
    for (const [id, entry] of this.entries) {
      if (entry.win.closed) {
        this.entries.delete(id);
        continue;
      }
      if (!eventMatchesAgent(event, id)) continue;
      this._addEvent(id, event);
      this._refreshEmpty(entry);
    }
  }

  closeAll() {
    for (const [, entry] of this.entries) {
      try {
        entry.win.close();
      } catch {
        // a popup the browser already took back cannot be closed again
      }
    }
    this.entries.clear();
  }

  /** One window: structure, stylesheet, and the handles live updates need. */
  _build(win, agent, runtimeState) {
    const doc = win.document;
    doc.title = `${agent.display_name || 'Agent'} · activitate live`;
    const head = doc.createElement('header');
    const title = doc.createElement('h1');
    title.textContent = `${agent.display_name || 'Agent'}${agent.role_name ? ` — ${agent.role_name}` : ''}`;
    const pill = doc.createElement('span');
    pill.className = 'pill';
    this._setPill(pill, runtimeState);
    head.append(title, pill);

    const now = doc.createElement('p');
    now.className = 'now';
    const nowLabel = doc.createElement('strong');
    nowLabel.textContent = 'Acum: ';
    const nowValue = doc.createElement('span');
    nowValue.textContent = nowLine(runtimeState, null);
    now.append(nowLabel, nowValue);

    const feed = doc.createElement('ol');
    feed.className = 'live-feed';

    const footer = doc.createElement('footer');
    footer.textContent = 'Flux în timp real din evenimentele studioului. Detaliile fiecărei acțiuni rămân în fereastra inspector.';

    doc.body.append(head, now, feed, footer);
    // The stylesheet must be constructed in the popup's own realm: a constructable sheet
    // built in the opener's document is refused by the popup's. CSSOM placement also keeps
    // the CSP intact — it forbids an inline <style>.
    if (typeof win.CSSStyleSheet === 'function' && 'adoptedStyleSheets' in doc) {
      try {
        const sheet = new win.CSSStyleSheet();
        sheet.replaceSync(LIVE_STYLES);
        doc.adoptedStyleSheets = [sheet];
      } catch {
        // unstyled popup still works
      }
    }
    return { win, pill, now: nowValue, feed, seen: new Set() };
  }

  _setPill(pill, runtimeState) {
    const state = String(runtimeState || 'IDLE');
    pill.textContent = state;
    pill.classList.toggle('is-busy', state === 'THINKING' || state === 'WORKING');
  }

  /** Put one event at the top of the feed; seeding relies on receiving newest first. */
  _addEvent(id, event) {
    const entry = this.entries.get(id);
    if (!entry || entry.win.closed) return;
    const dedupeKey = String(event.event_id || `${event.sequence}:${event.timestamp}:${event.event_type}`);
    if (entry.seen.has(dedupeKey)) return;
    entry.seen.add(dedupeKey);

    const info = describeEvent(event, this.names);
    const doc = entry.win.document;
    const row = doc.createElement('li');
    row.className = `live-row live-${info.kind}`;
    const time = doc.createElement('time');
    time.textContent = new Date(event.timestamp || Date.now()).toLocaleTimeString('ro-RO', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZone: this.timezone,
    });
    const body = doc.createElement('div');
    const head = doc.createElement('div');
    head.className = 'live-head';
    head.textContent = info.who ? `${info.who} ${info.label}` : info.label;
    body.append(head);
    if (info.text) {
      const text = doc.createElement('div');
      text.className = 'live-text';
      text.textContent = info.text;
      body.append(text);
    }
    row.append(time, body);
    entry.feed.insertBefore(row, entry.feed.firstChild);

    if (event.event_type === 'agent.state_changed') {
      const state = event.payload && event.payload.runtime_state;
      this._setPill(entry.pill, state);
      entry.now.textContent = nowLine(state, event.payload && event.payload.task_type);
    }
    if (event.event_type === 'agent.run_completed') {
      this._setPill(entry.pill, 'IDLE');
      entry.now.textContent = nowLine('IDLE', null);
    }
  }

  _refreshEmpty(entry) {
    if (entry.feed.children.length === 0 && !entry.feed.querySelector('.live-empty')) {
      const empty = entry.win.document.createElement('li');
      empty.className = 'live-empty';
      empty.textContent = 'Nimic înregistrat despre acest angajat încă. Când lucrează sau vorbește, apare aici instant.';
      entry.feed.append(empty);
    } else if (entry.feed.children.length > 1) {
      const empty = entry.feed.querySelector('.live-empty');
      if (empty) empty.remove();
    }
  }

  /** A popup whose opener is gone has no feed any more; close it instead of stranding it. */
  _watchdog() {
    for (const [id, entry] of this.entries) {
      if (entry.win.closed) {
        this.entries.delete(id);
        continue;
      }
      if (!entry.win.opener || entry.win.opener.closed) {
        try {
          entry.win.close();
        } catch {
          // best effort
        }
        this.entries.delete(id);
      }
    }
  }
}
