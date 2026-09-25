import { BUCHAREST, solarElevation } from './hq_time.js';

/**
 * THE STUDIO'S KEPT FRAME, FOR A FIRST VISIT'S TITLE (W24).
 *
 * Until W23 only a browser that had already watched the stream kept a real frame of the Unreal
 * building (stream_keep.js), so a stranger's first visit opened on the page renderer's title and
 * only then met Unreal's building. While the Owner's signed-in page plays the stream it now also
 * sends its newest kept frame to the studio, at most every STUDIO_SEND_EVERY_MS: the same small WebP,
 * with the moment it was captured (backend/app/office/kept_frame.py keeps the newest one). The
 * title reads it back before any key (a public, read-only GET: it shows only the building).
 *
 * A real frame is not the hour now. The title stands on a kept frame, the studio's or this
 * browser's, only while its light is the light outside now: the same solar state over Bucharest
 * (day, golden hour, twilight or night, and for the two in between the same half of the day, since
 * the morning sun lights the building from the other side), and only when it is not older than a
 * day. Otherwise the title stands on the plates, lit by the real sun, as before. A studio that does
 * not have the route (the Owner's running backend before a restart) answers 404, and a studio
 * with nothing kept 204: the plates.
 */

/** The route, on the page's own origin. */
export const STUDIO_FRAME_URL = '/api/v1/office/kept-frame';
/** The Owner's page sends a kept frame to the studio at most this often. */
export const STUDIO_SEND_EVERY_MS = 5 * 60 * 1000;
/** A kept frame older than this never stands on the title. */
export const TITLE_FRAME_MAX_AGE_MS = 24 * 3600 * 1000;
/** A capture time this far ahead of the clock is a wrong clock, not a frame. */
const FUTURE_SLACK_MS = 60000;

/**
 * The sun's bands over the building, in degrees of elevation. Day: the facade in full light. The
 * golden hour: the low sun, from 6 deg down to just under the horizon (refraction), warm and
 * raking. Twilight: the sun below the horizon to 12 deg down, the sky still lit and the city's
 * lamps on (scene_params.py switches them in civil twilight). Night: below that.
 */
export const SOLAR_BANDS = { golden: 6, twilight: -1, night: -12 };

/**
 * The solar state of a moment over Bucharest: 'day', 'night', or the golden hour and twilight with
 * the half of the day they fall in ('golden-morning', 'twilight-evening', …).
 * @param {number} ms @param {{lat: number, lon: number}} [place]
 * @returns {string}
 */
export function solarState(ms, place = BUCHAREST) {
  const at = new Date(ms);
  const e = solarElevation(at, place.lat, place.lon);
  if (e >= SOLAR_BANDS.golden) return 'day';
  if (e < SOLAR_BANDS.night) return 'night';
  const band = e >= SOLAR_BANDS.twilight ? 'golden' : 'twilight';
  // rising or setting: where the sun is ten minutes on
  const rising = solarElevation(new Date(ms + 600000), place.lat, place.lon) > e;
  return `${band}-${rising ? 'morning' : 'evening'}`;
}

/**
 * Whether a kept frame captured at `at` may stand on the title at `now`: a real past moment, not
 * older than a day, in the same solar state as now.
 * @param {number} at @param {number} now
 */
export function lightMatches(at, now) {
  if (!Number.isFinite(at) || !Number.isFinite(now)) return false;
  if (at > now + FUTURE_SLACK_MS || now - at > TITLE_FRAME_MAX_AGE_MS) return false;
  return solarState(at) === solarState(now);
}

/**
 * The frame the title stands on: of the kept frames offered (this browser's, the studio's), the
 * newest whose light matches now. Null when none does: the title stands on the plates.
 * @template {{at: number}} T
 * @param {Array<T|null|undefined>} frames @param {number} now
 * @returns {T|null}
 */
export function chooseTitleFrame(frames, now) {
  let best = /** @type {T|null} */ (null);
  for (const frame of frames) {
    if (!frame || !lightMatches(Number(frame.at), now)) continue;
    if (!best || Number(frame.at) > Number(best.at)) best = frame;
  }
  return best;
}

/**
 * Whether the Owner's page sends its kept frame to the studio now: a backend that has the route,
 * and the last send at least STUDIO_SEND_EVERY_MS ago.
 * @param {{supported: boolean, lastSent: number}} state @param {number} now
 */
export function studioSendDue(state, now) {
  return Boolean(state.supported) && (!(state.lastSent > 0) || now - state.lastSent >= STUDIO_SEND_EVERY_MS);
}

/**
 * The studio's kept frame, read before any key: its bytes and its capture time, or null (nothing
 * kept, a studio without the route, anything that is not a WebP with a time, a failed read).
 * @param {typeof fetch} fetcher @param {number} [timeoutMs]
 * @returns {Promise<{blob: Blob, at: number}|null>}
 */
export async function readStudioFrame(fetcher, timeoutMs = 4000) {
  try {
    const response = await fetcher(STUDIO_FRAME_URL, { cache: 'no-store', signal: AbortSignal.timeout(timeoutMs) });
    if (!response || !response.ok) return null;
    const type = String(response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
    const at = Number(response.headers.get('x-captured-at'));
    if (type !== 'image/webp' || !Number.isFinite(at) || at <= 0) return null;
    const blob = await response.blob();
    return blob && blob.size > 0 ? { blob, at } : null;
  } catch {
    return null;
  }
}

/**
 * Sends a kept frame to the studio with the Owner's key (a header, never the URL).
 * 'stored' (kept, or a newer one was already kept), 'unsupported' (a studio without the route: the
 * page stops sending for this visit), 'failed' (anything else; the next due send tries again).
 * @param {typeof fetch} fetcher @param {string} key @param {{blob: Blob, at: number}} record
 * @returns {Promise<'stored'|'unsupported'|'failed'>}
 */
export async function sendStudioFrame(fetcher, key, record) {
  if (!key || !record || !record.blob || !Number.isFinite(Number(record.at))) return 'failed';
  try {
    const response = await fetcher(STUDIO_FRAME_URL, {
      method: 'POST',
      body: record.blob,
      cache: 'no-store',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'image/webp', 'X-Captured-At': String(Math.round(Number(record.at))) },
      signal: AbortSignal.timeout(15000),
    });
    if (response.ok) return 'stored';
    return response.status === 404 || response.status === 405 ? 'unsupported' : 'failed';
  } catch {
    return 'failed';
  }
}
