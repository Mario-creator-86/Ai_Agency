/**
 * The live Unreal headquarters is streamed into the page over Pixel Streaming. scene.json says
 * whether the page shows it; the backend says whether a stream is configured and relays its
 * signalling on the page's own origin. Whenever either says no, or the stream is not running, the
 * page shows its own renderer.
 */

/**
 * @typedef {{enabled: boolean, streamerId: string, retryMs: number}} LiveStreamSettings
 */

const DEFAULT_RETRY_MS = 15000;

/**
 * @param {any} scene the parsed scene.json (or null when it failed to load)
 * @returns {LiveStreamSettings}
 */
export function liveStreamSettings(scene) {
  const block = scene && typeof scene === 'object' ? scene.live_stream : null;
  if (!block || typeof block !== 'object' || block.enabled !== true) {
    return { enabled: false, streamerId: '', retryMs: DEFAULT_RETRY_MS };
  }
  const retry = Number(block.retry_ms);
  return {
    enabled: true,
    streamerId: typeof block.streamer_id === 'string' ? block.streamer_id.trim() : '',
    retryMs: Number.isFinite(retry) && retry >= 1000 ? retry : DEFAULT_RETRY_MS,
  };
}

/**
 * Under reduced motion the stream is shown as one real frame of it, renewed this often (W18: the
 * street's traffic drove past at 38 fps for a visitor whose system asks for reduced motion, while
 * the page's own renderer holds the street still for them).
 */
export const HELD_STILL_MS = 10000;

/**
 * What the stream layer shows for a status, once the backend has a stream configured. Live, the
 * video, or, when the visitor's system asks for reduced motion (`held`), a real frame of it kept
 * and renewed every HELD_STILL_MS. Otherwise never the page's own renderer, whose older picture of
 * the headquarters the Owner does not want to see ("Încă apare vechiul format!"): after a frame has
 * been kept, that frame, frozen, with a note that the page is reconnecting. Before this visit's
 * first frame (W19): the last live frame an earlier visit kept in this browser (`kept`, stream_keep.js),
 * dimmed and named «ultimul cadru live · <zi> <ora>», until the live video's first frame; with none
 * kept (a first visit, or storage refused), a dark viewport saying the live headquarters is
 * starting. The renderer keeps running underneath, so clicks still find the employees.
 * @param {'connecting'|'live'|'offline'} status
 * @param {boolean} hasStill whether a frame of this visit's stream has been kept
 * @param {boolean} [held] whether the visitor's system asks for reduced motion
 * @param {boolean} [kept] whether an earlier visit's last live frame is on the plate
 * @returns {{still: boolean, waiting: boolean, note: '' | 'reconnecting' | 'starting' | 'kept', held: boolean, kept: boolean}}
 */
export function streamLayers(status, hasStill, held = false, kept = false) {
  if (status === 'live') return held ? { still: true, waiting: false, note: '', held: true, kept: false } : { still: false, waiting: false, note: '', held: false, kept: false };
  if (hasStill) return { still: true, waiting: false, note: 'reconnecting', held: false, kept: false };
  if (kept) return { still: true, waiting: false, note: 'kept', held: false, kept: true };
  return { still: false, waiting: true, note: 'starting', held: false, kept: false };
}

/**
 * HOW THE PAGE'S SOCKETS SAY THE OWNER'S KEY (2026-09-25). A browser cannot set a header on a
 * WebSocket, so the key used to travel in the socket's URL (…?token=…), which the browser prints
 * when the socket fails and which proxy and server access logs keep. A backend that says
 * `auth: 'first_message'` on GET /office/stream takes the key as each socket's first message.
 * SEC-02 (2026-10-01): the key is never put in a URL again, by any page. uvicorn logs a socket's
 * path with its query, so the backend refuses such a socket, and a route that does not say
 * 'first_message' ('query') means the live stream is not opened at all: the page keeps its own
 * renderer and says why (STREAM_NO_SAFE_AUTH).
 * @param {any} route the answer of GET /office/stream, or null when it could not be read
 * @returns {'first_message'|'query'}
 */
export function socketAuth(route) {
  return route && typeof route === 'object' && route.auth === 'first_message' ? 'first_message' : 'query';
}

/** What the page says when the live stream cannot be given the key safely. */
export const STREAM_NO_SAFE_AUTH = 'Sediul live nu poate primi cheia în siguranță (doar ca prim mesaj, niciodată în adresă); pagina își arată propria randare.';

/**
 * The first message of a socket that authenticates by it.
 * @param {string} token
 */
export function authMessage(token) {
  return JSON.stringify({ type: 'auth', token: String(token || '') });
}

/** @param {{protocol: string}} location */
const wsScheme = (location) => (location.protocol === 'https:' ? 'wss' : 'ws');

/**
 * The backend's relay for the stream's signalling, on the page's own origin. It never carries the
 * key (SEC-02): the key is the socket's first message (authMessage).
 * @param {{protocol: string, host: string}} location
 * @param {string} relayPath from GET /office/stream
 */
export function relayUrl(location, relayPath) {
  const path = relayPath.startsWith('/') ? relayPath : `/${relayPath}`;
  return `${wsScheme(location)}://${location.host}${path}`;
}

/**
 * The backend's events socket (/api/v1/ws). It never carries the key (SEC-02).
 * @param {{protocol: string, host: string}} location
 */
export function eventsUrl(location) {
  return `${wsScheme(location)}://${location.host}/api/v1/ws`;
}

/**
 * W23: a line for the console with the value of every `token=` blanked. The Pixel Streaming
 * library prints the signalling URL on every connect; against a backend that still takes the key
 * in the URL (the Owner's running studio, until he restarts it) that line carried his key.
 * @param {unknown} message
 */
export function redactKey(message) {
  return String(message).replace(/([?&]token=)[^&#\s'"`]*/gi, '$1…');
}

/**
 * The library's logger, with every line passed through redactKey first. Wrapping it twice is
 * wrapping it once.
 * @param {any} base the library's Logger
 */
export function redactingLogger(base) {
  if (!base || base.redactsKey) return base;
  return {
    redactsKey: true,
    InitLogging: (/** @type {number} */ level, /** @type {boolean} */ stack) => base.InitLogging(level, stack),
    Debug: (/** @type {string} */ m) => base.Debug(redactKey(m)),
    Info: (/** @type {string} */ m) => base.Info(redactKey(m)),
    Warning: (/** @type {string} */ m) => base.Warning(redactKey(m)),
    Error: (/** @type {string} */ m) => base.Error(redactKey(m)),
  };
}

/**
 * W23: the browser's first answer to RTCRtpReceiver.getCapabilities('video') in a fresh process
 * enumerates its codecs synchronously, about one second on the Owner's machine; later answers are
 * immediate. The Pixel Streaming library asks when it is built, which on a first visit was in the
 * middle of the entry. The page asks once itself, earlier, while the title stands idle.
 * @param {any} win the window
 * @returns {boolean} whether the browser was asked
 */
export function warmVideoCodecs(win) {
  try {
    const receiver = win && win.RTCRtpReceiver;
    if (!receiver || typeof receiver.getCapabilities !== 'function') return false;
    receiver.getCapabilities('video');
    return true;
  } catch {
    return false;
  }
}

/** What the relay says once the key is right and the signalling server has answered. */
export const RELAY_READY = 'relay_ready';

/** @param {any} data a message of the signalling socket */
export function isRelayReady(data) {
  if (typeof data !== 'string' || data.length > 64 || !data.includes(RELAY_READY)) return false;
  try {
    const message = JSON.parse(data);
    return Boolean(message) && message.type === RELAY_READY;
  } catch {
    return false;
  }
}

/**
 * Lays first-message auth on Pixel Streaming's signalling transport (the library's
 * WebSocketTransport, which opens the socket itself). When its socket opens, the key goes out as
 * the first message and the library is not yet told; it is told the socket is open only when the
 * relay says «relay_ready», so it starts exactly as it did when the relay accepted the socket
 * after reaching the signalling server, and a relay that closes first is, to the library, a
 * socket that never opened. Nothing before «relay_ready» reaches the library.
 * @param {any} transport the library's transport (PixelStreaming.webRtcController.transport)
 * @param {() => string} message the auth message, read at each connect
 * @returns {boolean} whether the transport could be taken; false leaves it untouched
 */
export function authenticateTransport(transport, message) {
  const t = transport;
  if (!t || typeof t.handleOnOpen !== 'function' || typeof t.handleOnMessage !== 'function' || typeof t.sendMessage !== 'function') return false;
  const open = t.handleOnOpen.bind(t);
  const receive = t.handleOnMessage.bind(t);
  let ready = false;
  t.handleOnOpen = () => {
    ready = false;
    t.sendMessage(message());
  };
  t.handleOnMessage = (/** @type {any} */ event) => {
    if (ready) {
      receive(event);
      return;
    }
    if (isRelayReady(event && event.data)) {
      ready = true;
      open();
    }
  };
  return true;
}

/**
 * A DEAD STREAM IS SAID (2026-09-25). Before, the plate said «Pornește sediul live…» for as long as
 * the live headquarters did not answer, ten minutes as readily as one second. After this many
 * failed connects in a row, or this long without a live picture, it says the headquarters is not
 * answering; the page keeps asking all the same.
 */
export const STREAM_SILENT_FAILURES = 3;
export const STREAM_SILENT_MS = 20000;

/**
 * @param {number} failures connects that failed since the stream was last live
 * @param {boolean} waitedLong whether STREAM_SILENT_MS has passed without a live picture
 */
export function streamSilent(failures, waitedLong) {
  return (Number(failures) || 0) >= STREAM_SILENT_FAILURES || Boolean(waitedLong);
}

/** The plate's words (glossary W19, W21). */
export const PLATE_NOTES = {
  reconnecting: 'Se reconectează la sediul live…',
  starting: 'Pornește sediul live…',
  silent: 'Sediul live nu răspunde · se încearcă din nou…',
};

/**
 * What the plate's badge says for a note of streamLayers.
 * @param {'' | 'reconnecting' | 'starting' | 'kept'} note
 * @param {boolean} silent streamSilent
 * @param {string} [keptCaption] the kept frame's name, as «ultimul cadru live · azi 22:48» reads
 */
export function plateNote(note, silent, keptCaption = '') {
  if (note === 'kept') return `${keptCaption} · ${silent ? 'sediul live nu răspunde' : 'pornește sediul live…'}`;
  if (note === 'starting' || note === 'reconnecting') return silent ? PLATE_NOTES.silent : PLATE_NOTES[note];
  return '';
}
