/**
 * Every "live" the page says, decided in one place from the states that make it true.
 *
 * The Owner's rule: nothing in the office view is simulated. A pulse, a figure or the word
 * «Live» must stand for something that is happening now. Three things can be happening, and
 * each is read, never assumed:
 *
 *   - the Unreal stream (hq_stream.js): `live` while its video plays, `connecting`/`offline`
 *     while it is (re)negotiating, over a frozen last frame when one was kept;
 *   - the events socket (main.js): `open` while the backend's events reach the page,
 *     `connecting` for the first time, `reconnecting` after a drop, `refused` when the backend
 *     turned the key away;
 *   - the snapshot (main.js, refresh): `stale` when the last read of the studio failed.
 *
 * The frame rate beside «Live» names what it measures: while the stream plays it is the frames
 * per second the page receives from Unreal (Pixel Streaming's own inbound statistics); while
 * the page draws the office itself it is that renderer's rate, and says so. A number that
 * belongs to one of them is never printed under the name of the other.
 */

/**
 * @typedef {'pending'|'off'|'connecting'|'live'|'offline'} StreamState
 * @typedef {'connecting'|'open'|'reconnecting'|'refused'|'closed'} SocketState
 * @typedef {{stream: StreamState, hasStill: boolean, socket: SocketState, data: 'fresh'|'stale',
 *            streamFps: number|null, pageFps: number|null}} LiveSignals
 * @typedef {{state: 'live'|'frozen'|'starting'|'reconnecting'|'stale'|'offline',
 *            live: boolean, hidden: boolean, parts: Array<[string, string]>, title: string}} Readout
 */

/** The backend closes the socket with this code when the Owner key is wrong: asking again cannot help. */
export const SOCKET_REFUSED = 1008;

/** The first wait after a drop, doubled on every failed try, up to the cap. */
export const SOCKET_RETRY_FIRST_MS = 1000;
export const SOCKET_RETRY_CAP_MS = 30000;

/**
 * How long the page waits before asking the events socket again after its `attempt`-th failure
 * (0 for the first): 1 s, 2 s, 4 s, 8 s, 16 s, then every 30 s. A backend restart takes a few
 * seconds on this machine; a longer outage costs one quiet attempt every half minute.
 * @param {number} attempt
 */
export function socketRetryMs(attempt) {
  const n = Math.max(0, Math.floor(Number(attempt) || 0));
  return Math.min(SOCKET_RETRY_CAP_MS, SOCKET_RETRY_FIRST_MS * 2 ** Math.min(n, 16));
}

/** A frame rate worth printing: a finite, non-negative number, rounded. Anything else is not shown. */
function figure(fps) {
  return typeof fps === 'number' && Number.isFinite(fps) && fps >= 0 ? `${Math.round(fps)}fps` : '';
}

const TITLES = {
  stream: 'Sediul din Unreal, transmis live prin Pixel Streaming. Cifra: cadrele pe secundă pe care pagina le primește de la Unreal.',
  page: 'Biroul desenat de pagină din starea reală a studioului, primită live de la backend. Cifra: cadrele pe secundă desenate de pagină, nu de Unreal.',
  frozen: 'Transmisia din Unreal s-a întrerupt. Se vede ultimul cadru primit, oprit, până revine.',
  reconnecting: 'Legătura cu evenimentele studioului s-a întrerupt. Pagina se reconectează singură.',
  stale: 'Ultima citire a studioului a eșuat. Ce se vede poate fi vechi.',
  offline: 'Backendul a refuzat legătura cu evenimentele studioului.',
};

/**
 * What the readout in the corner of the render says, and whether it may call itself live.
 * @param {LiveSignals} signals
 * @returns {Readout}
 */
export function sceneReadout(signals) {
  const { stream, hasStill, socket, data } = signals;
  if (data === 'stale') {
    return { state: 'stale', live: false, hidden: false, parts: [['scene-live', 'Date neactualizate']], title: TITLES.stale };
  }
  if (stream === 'live') {
    const fps = figure(signals.streamFps);
    const parts = /** @type {Array<[string, string]>} */ ([['scene-live', 'Live'], ['scene-label', fps ? ' · Unreal ' : ' · Unreal']]);
    if (fps) parts.push(['scene-figure', fps]);
    return { state: 'live', live: true, hidden: false, parts, title: TITLES.stream };
  }
  if (stream === 'connecting' || stream === 'offline') {
    // Over the last frame, kept and frozen: it says it is a frozen frame and that the page is
    // reconnecting. Before any frame the viewport's own plate says the headquarters is starting,
    // and a second voice in the corner would repeat it.
    if (hasStill) {
      return {
        state: 'frozen',
        live: false,
        hidden: false,
        parts: [['scene-live', 'Se reconectează'], ['scene-label', ' · cadru înghețat']],
        title: TITLES.frozen,
      };
    }
    return { state: 'starting', live: false, hidden: true, parts: [], title: '' };
  }
  // No stream: the page draws the office itself, from the backend's events. It is live only while
  // those events can reach it.
  if (socket === 'open') {
    const fps = figure(signals.pageFps);
    const parts = /** @type {Array<[string, string]>} */ ([['scene-live', 'Live'], ['scene-label', fps ? ' · randarea paginii ' : ' · randarea paginii']]);
    if (fps) parts.push(['scene-figure', fps]);
    return { state: 'live', live: true, hidden: false, parts, title: TITLES.page };
  }
  if (socket === 'refused' || socket === 'closed') {
    return { state: 'offline', live: false, hidden: false, parts: [['scene-live', 'Deconectat']], title: TITLES.offline };
  }
  return {
    state: 'reconnecting',
    live: false,
    hidden: false,
    parts: [['scene-live', socket === 'connecting' ? 'Se conectează' : 'Se reconectează']],
    title: TITLES.reconnecting,
  };
}

/**
 * The connection chip in the masthead.
 * @param {{data: 'fresh'|'stale', socket: SocketState}} signals
 */
export function connectionLabel(signals) {
  if (signals.data === 'stale') return 'Deconectat';
  switch (signals.socket) {
    case 'open':
      return 'Conectat · Proprietar';
    case 'connecting':
      return 'Se conectează…';
    case 'reconnecting':
      return 'Se reconectează…';
    default:
      return 'Deconectat';
  }
}

/**
 * The caption on the slate under the render: how many employees, and «live» only while it is.
 * «12 angajați», «1 angajat», «20 de angajați»: the `de` a Romanian speaker cannot leave out.
 * @param {number} staff
 * @param {boolean} live
 */
export function roomCaption(staff, live) {
  const place = live ? 'sediul AMN-AI, live' : 'sediul AMN-AI';
  if (!staff) return place[0].toUpperCase() + place.slice(1);
  return `${staff}${staff >= 20 ? ' de' : ''} ${staff === 1 ? 'angajat' : 'angajați'} la birourile lor · ${place}`;
}

/** How many events one replay request asks for (the backend's own cap is 500). */
export const REPLAY_PAGE = 500;
/** A replay that filled its page is asked to continue, up to this many pages after one drop. */
export const REPLAY_MAX_PAGES = 10;
/** The socket is asked «ping» this often; the backend answers «pong». */
export const SOCKET_PING_MS = 25000;
/** Nothing at all heard for this long — not an event, not a pong — and the socket is treated as dead. */
export const SOCKET_SILENT_MS = 60000;

/**
 * The page's link to the backend's events (/api/v1/ws): it connects, replays what the page has
 * not seen, reconnects after a drop with a growing pause, and says which of its states it is in.
 *
 * Until 2026-09-24 the page opened the socket once and never again: a backend restart left the
 * register and the office frozen while the corner still said «Live». Now a drop is followed by
 * `reconnecting` (the page says so), a retry after socketRetryMs, and on the way back a replay
 * from the newest sequence the page holds, in pages, so nothing recorded during the gap is lost.
 * A refusal of the key (code 1008) is final: asking again with the same key cannot succeed.
 *
 * Everything the link touches is handed in, so the tests drive it without a browser.
 */
export class EventsLink {
  /**
   * @param {{
   *   url: () => string,
   *   open: (url: string) => any,
   *   afterSequence: () => number,
   *   onEvent: (event: any, live: boolean) => void,
   *   onState: (state: SocketState) => void,
   *   onReconnected?: () => void,
   *   timers?: {setTimeout: Function, clearTimeout: Function, setInterval: Function, clearInterval: Function},
   *   now?: () => number,
   * }} options
   */
  constructor(options) {
    this.options = options;
    this.timers = options.timers || globalThis;
    this.now = options.now || (() => Date.now());
    /** @type {SocketState} */
    this.state = 'closed';
    this.socket = null;
    this.attempt = 0;
    this.everOpened = false;
    this.retryTimer = 0;
    this.pingTimer = 0;
    this.heardAt = 0;
    this.replayPages = 0;
    this.stopped = true;
  }

  start() {
    this.stop();
    this.stopped = false;
    this.everOpened = false;
    this.attempt = 0;
    this._setState('connecting');
    this._connect();
  }

  /** Closes the socket and asks nothing again (sign-out). */
  stop() {
    this.stopped = true;
    this.timers.clearTimeout(this.retryTimer);
    this.timers.clearInterval(this.pingTimer);
    this.retryTimer = 0;
    this.pingTimer = 0;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
      try { socket.close(); } catch { /* already closed */ }
    }
    if (this.state !== 'closed') this._setState('closed');
  }

  /** @param {SocketState} state */
  _setState(state) {
    if (this.state === state) return;
    this.state = state;
    this.options.onState(state);
  }

  _connect() {
    let socket;
    try {
      socket = this.options.open(this.options.url());
    } catch {
      this._dropped(0);
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket !== socket) return;
      const reconnected = this.everOpened;
      this.everOpened = true;
      this.attempt = 0;
      this.heardAt = this.now();
      this.replayPages = 0;
      this._setState('open');
      this._replay(this.options.afterSequence());
      this.timers.clearInterval(this.pingTimer);
      this.pingTimer = this.timers.setInterval(() => this._ping(), SOCKET_PING_MS);
      if (reconnected && this.options.onReconnected) this.options.onReconnected();
    };
    socket.onmessage = (/** @type {{data: any}} */ message) => {
      if (this.socket !== socket) return;
      this.heardAt = this.now();
      let payload;
      try {
        payload = JSON.parse(message.data);
      } catch {
        return;
      }
      if (payload && (payload.type === 'event' || payload.type === 'replay_event')) {
        // `live` is whether the backend sent it as it happened (`event`) or as history the page
        // asked for (`replay_event`): only the first may play a moment (moments.js).
        this.options.onEvent(payload.data, payload.type === 'event');
      } else if (payload && payload.type === 'replay_complete') {
        // A full page means there may be more: ask from where it ended.
        if (Number(payload.count) >= REPLAY_PAGE && this.replayPages < REPLAY_MAX_PAGES) {
          this._replay(Number(payload.up_to_sequence) || 0);
        }
      }
    };
    socket.onerror = () => {};
    socket.onclose = (/** @type {{code?: number}} */ event) => {
      if (this.socket !== socket) return;
      this._dropped(event && event.code);
    };
  }

  /** @param {number} after */
  _replay(after) {
    this.replayPages += 1;
    this._send({ type: 'replay', after_sequence: Math.max(0, Number(after) || 0), limit: REPLAY_PAGE });
  }

  _ping() {
    if (this.state !== 'open') return;
    if (this.now() - this.heardAt > SOCKET_SILENT_MS) {
      // Half-open: the backend went away without a close. Close it ourselves and start again.
      const socket = this.socket;
      this.socket = null;
      if (socket) {
        socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
        try { socket.close(); } catch { /* already gone */ }
      }
      this._dropped(0);
      return;
    }
    this._send({ type: 'ping' });
  }

  /** @param {any} message */
  _send(message) {
    try {
      if (this.socket) this.socket.send(JSON.stringify(message));
    } catch { /* the close handler takes it from here */ }
  }

  /** @param {number|undefined} code */
  _dropped(code) {
    this.timers.clearInterval(this.pingTimer);
    this.pingTimer = 0;
    this.socket = null;
    if (this.stopped) return;
    if (code === SOCKET_REFUSED) {
      this.stopped = true;
      this._setState('refused');
      return;
    }
    this._setState(this.everOpened ? 'reconnecting' : 'connecting');
    this.timers.clearTimeout(this.retryTimer);
    this.retryTimer = this.timers.setTimeout(() => {
      this.retryTimer = 0;
      if (!this.stopped) this._connect();
    }, socketRetryMs(this.attempt));
    this.attempt += 1;
  }
}
