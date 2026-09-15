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
 * What the stream layer shows for a status, once the backend has a stream configured. Live, the
 * video. Otherwise never the page's own renderer, whose older picture of the headquarters the
 * Owner does not want to see ("Încă apare vechiul format!"): after a frame has been kept, that
 * frame, frozen, with a note that the page is reconnecting; before any frame (Unreal not started
 * yet, or being rebuilt), a dark viewport saying the live headquarters is starting. The renderer
 * keeps running underneath, so clicks still find the employees.
 * @param {'connecting'|'live'|'offline'} status
 * @param {boolean} hasStill whether a frame of the stream has been kept
 * @returns {{still: boolean, waiting: boolean, note: '' | 'reconnecting' | 'starting'}}
 */
export function streamLayers(status, hasStill) {
  if (status === 'live') return { still: false, waiting: false, note: '' };
  if (hasStill) return { still: true, waiting: false, note: 'reconnecting' };
  return { still: false, waiting: true, note: 'starting' };
}

/**
 * The backend's relay for the stream's signalling, on the page's own origin.
 * @param {{protocol: string, host: string}} location
 * @param {string} relayPath from GET /office/stream
 * @param {string} token the Owner token the page already holds
 */
export function relayUrl(location, relayPath, token) {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  const path = relayPath.startsWith('/') ? relayPath : `/${relayPath}`;
  return `${scheme}://${location.host}${path}?token=${encodeURIComponent(token)}`;
}
