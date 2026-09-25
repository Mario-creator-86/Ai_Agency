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
  if (runtimeState === 'PAUSED') return 'în pauză';
  return 'nicio sarcină în lucru';
}

/**
 * The popup's stylesheet, through CSSOM because the CSP forbids an inline `<style>`.
 *
 * WHY THE PALETTE IS WRITTEN OUT AGAIN HERE. A popup is a separate document: it cannot
 * import the page's stylesheet, and a constructable sheet built in the opener's realm is
 * refused by the popup's own, so the values have to be copied into the file. The source of
 * truth is the `:root` block at the top of `frontend/src/style.css` — every custom property
 * below is a verbatim copy of the one there, under the same name, and a token that changes
 * there has to be changed here in the same commit or this window drifts away from the page
 * it belongs to. Nothing below states a colour, a size, a radius or a shadow of its own;
 * the rules use the tokens exactly as the page's own rules do.
 *
 * Two properties are this document's own, because the page has no equivalent, and both say
 * so where they are declared. There is no transition, no animation and no scripted smooth
 * scroll anywhere in this sheet: nothing here moves, so `prefers-reduced-motion` has
 * nothing to switch off.
 */
const LIVE_STYLES = `
:root {
  /* --- copied from the :root block of frontend/src/style.css --------------- */
  --bg:            #05080e;
  --surface:       #0d131e;
  --surface-quiet: #161e2e;
  --line:          #1e2839;
  --line-strong:   #2d3b53;
  --ink:           #eaf0fb;
  --ink-2:         #a9b6cc;
  --ink-3:         #8a98b2;
  --forest-deep:   #0a1512;
  --forest-ink:    #63c9a9;
  --gold:          #e0b062;
  --warn-bg:       #2a2011;
  --warn-line:     #5c4620;
  --warn-ink:      #f0c887;
  --alert-ink:     #ff9d8f;
  --info-ink:      #7ad4ea;
  --radius-sm:     8px;
  --radius-pill:   999px;
  --lit-edge:      inset 0 1px 0 rgba(255, 255, 255, .13);
  --font-sans:     "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, "Inter", "Helvetica Neue", Arial, sans-serif;
  --font-mono:     ui-monospace, "Cascadia Mono", "SF Mono", Consolas, monospace;
  --track-caps:    .16em;
  --fs-micro:      10px;
  --fs-meta:       11.5px;
  --fs-body:       13px;
  --fs-h3:         15px;
  --lh-snug:       1.4;
  --lh-body:       1.6;
  --w-semi:        600;
  --w-bold:        700;
  --s1: 4px;  --s2: 8px;  --s3: 12px; --s4: 16px; --s5: 20px;
  /* --- this document's own, because the page has nothing that does this job - */
  /* The page's ledger rail is --time-rail (54px) and shows HH:MM. This window
     is watching one employee work, so it shows the second as well, and eight
     mono figures do not fit in 54. */
  --live-rail: 62px;
  /* The window is a column: header, the standing line, the feed, and the caption
     directly under whatever the feed holds — not pinned to the floor of an empty
     window. --live-foot is the caption's own room when the feed does fill. */
  --live-foot: var(--s2);
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  background: var(--bg);
  color: var(--ink);
  font: var(--fs-body)/var(--lh-body) var(--font-sans);
  font-variant-numeric: tabular-nums;
  font-synthesis: none;
}
header {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  background: var(--forest-deep);
  color: var(--ink);
  border-bottom: 1px solid var(--line);
  box-shadow: var(--lit-edge);
}
header h1 { margin: 0; font-size: var(--fs-h3); font-weight: var(--w-semi); letter-spacing: -.015em; }
.pill {
  font-size: var(--fs-micro);
  font-weight: var(--w-bold);
  letter-spacing: var(--track-caps);
  padding: var(--s1) var(--s3);
  border-radius: var(--radius-pill);
  background: var(--surface-quiet);
  color: var(--ink-3);
  border: 1px solid var(--line-strong);
  white-space: nowrap;
}
.pill.is-busy { background: var(--warn-bg); color: var(--warn-ink); border-color: var(--warn-line); }
.now {
  margin: 0;
  padding: var(--s3) var(--s4);
  font-size: var(--fs-meta);
  color: var(--ink-2);
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.now strong { color: var(--ink); }
.live-feed {
  list-style: none;
  margin: 0;
  padding: var(--s2) var(--s4) var(--live-foot);
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}
.live-row {
  display: grid;
  grid-template-columns: var(--live-rail) minmax(0, 1fr);
  gap: var(--s2);
  padding: var(--s2);
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 3px solid var(--line-strong);
  border-radius: var(--radius-sm);
}
.live-row time {
  font-family: var(--font-mono);
  font-size: var(--fs-meta);
  letter-spacing: -.03em;
  color: var(--ink-3);
  padding-top: 1px;
  font-variant-numeric: tabular-nums;
}
.live-head { color: var(--ink-2); line-height: var(--lh-snug); }
.live-head strong { color: var(--ink); font-weight: 650; }
.live-text { color: var(--ink-3); margin-top: 2px; line-height: var(--lh-snug); overflow-wrap: anywhere; white-space: pre-wrap; }
/* The kind rails, the same four meanings and the same four colours the ledger
   on the page gives them: what an employee said, what the studio produced,
   what it cost, and what is for the Owner. */
.live-speech { border-left-color: var(--forest-ink); }
.live-production { border-left-color: var(--info-ink); }
.live-money { border-left-color: var(--gold); }
.live-owner { border-left-color: var(--alert-ink); }
.live-empty { padding: var(--s5) var(--s4); color: var(--ink-3); font-style: italic; }
footer {
  /* The caption follows the feed, and when the feed is short it still closes the
     window instead of floating in the middle of it: measured 2026-09-23, three
     entries left the caption at y335 with 430px of bare ground under it. */
  margin-top: auto;
  padding: var(--s2) var(--s4);
  font-size: var(--fs-micro);
  color: var(--ink-3);
  background: var(--surface);
  border-top: 1px solid var(--line);
}
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
    // W28: the name already says the role («Dr. Aris (Researcher)»); the code is its tooltip
    title.textContent = agent.display_name || 'Agent';
    if (agent.role_name) title.title = agent.role_name;
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
    footer.textContent = 'Flux live din evenimentele studioului. Detaliile fiecărei acțiuni rămân în fereastra de inspecție.';

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
      empty.textContent = 'Nimic înregistrat despre acest angajat încă. Când lucrează sau vorbește, apare aici imediat.';
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
