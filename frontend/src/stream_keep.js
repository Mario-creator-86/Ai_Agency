import { studioPlace } from './office_clock.js';

/**
 * THE LAST LIVE FRAME, KEPT FOR THE NEXT ENTRY (W19).
 *
 * Between the key and the stream's first picture the frame was dark for 1.0-2.5 s («Pornește
 * sediul live…»). While the stream plays, the page now keeps one real frame of it — a WebP at
 * the stream's own width (KEEP_WIDTH), taken rarely (KEEP_FIRST_MS after the first frame, then every KEEP_EVERY_MS),
 * never per frame — with the moment it was taken, in this browser's IndexedDB. On the next entry
 * the starting plate shows that frame, dimmed and named for what it is («ultimul cadru live · azi
 * 22:48»), until the live video's first frame arrives, and then gives way to it.
 *
 * It is a per-browser convenience, never a record: every access is inside try/catch and under a
 * timeout, and a browser that refuses storage (a private window, cleared or blocked site data)
 * simply has no kept frame and keeps the dark plate. Nothing is fetched and nothing is sent.
 */

/** How long after the stream's first live frame the first frame is kept. */
export const KEEP_FIRST_MS = 4000;
/** How often, while the stream plays, the kept frame is renewed. */
export const KEEP_EVERY_MS = 60000;
/**
 * The kept frame's width in px: the stream's own 1920 (never enlarged). W19 kept 960 for the plate,
 * where it is seen dimmed for a moment; since W22 the title stands on it as its key art, drawn at
 * 1.3-1.8 CSS px per world px, where a 960 px frame read soft.
 */
export const KEEP_WIDTH = 1920;
export const KEEP_TYPE = 'image/webp';
export const KEEP_QUALITY = 0.72;
/** A kept frame older than this is not shown: the building it shows may have been rebuilt since. */
export const KEEP_MAX_AGE_MS = 30 * 24 * 3600 * 1000;
/** A storage that does not answer in this long is treated as having nothing. */
const STORE_TIMEOUT_MS = 1500;

const DB_NAME = 'amn-ai-hq';
const STORE = 'kept';
const KEY = 'last-live-frame';

const WEEKDAYS = ['duminică', 'luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă'];

/**
 * The kept frame's size: the stream's own aspect, at most `max` px wide, never enlarged.
 * @param {number} w @param {number} h @param {number} [max]
 * @returns {{w: number, h: number}|null}
 */
export function keptSize(w, h, max = KEEP_WIDTH) {
  if (!(w > 0) || !(h > 0)) return null;
  const k = Math.min(1, max / w);
  return { w: Math.max(1, Math.round(w * k)), h: Math.max(1, Math.round(h * k)) };
}

/**
 * Calendar day and hour of an instant in the studio's zone.
 * @param {number} ms @param {string|undefined} timeZone
 */
function parts(ms, timeZone) {
  const f = new Intl.DateTimeFormat('en-GB', { timeZone: timeZone || studioPlace().timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  /** @type {Record<string, string>} */
  const p = {};
  for (const x of f.formatToParts(new Date(ms))) p[x.type] = x.value;
  return { y: Number(p.year), m: Number(p.month), d: Number(p.day), hm: `${p.hour}:${p.minute}` };
}

/**
 * What the kept frame is called on the plate: «ultimul cadru live · <zi> <ora>». The day is
 * «azi», «ieri», the weekday within the week, else the date; the hour is the studio's.
 * @param {number} at when the frame was taken (ms) @param {number} now @param {string} [timeZone]
 */
export function keptCaption(at, now, timeZone) {
  const when = keptDay(at, now, timeZone);
  return when ? `ultimul cadru live · ${when.day} ${when.hm}` : '';
}

/**
 * The day and hour of a real frame, as the page names them (W22, shared by the plate's badge, the
 * title's caption and the replay's line): «azi», «ieri», the weekday within the week, else the
 * date (`dated`), and the hour in the studio's zone. Null for a moment that is not one.
 * @param {number} at @param {number} now @param {string} [timeZone]
 * @returns {{day: string, hm: string, dated: boolean}|null}
 */
export function keptDay(at, now, timeZone) {
  if (!Number.isFinite(at)) return null;
  const a = parts(at, timeZone);
  const n = parts(now, timeZone);
  const days = Math.round((Date.UTC(n.y, n.m - 1, n.d) - Date.UTC(a.y, a.m - 1, a.d)) / 86400000);
  const weekday = WEEKDAYS[new Date(Date.UTC(a.y, a.m - 1, a.d)).getUTCDay()];
  const dated = days >= 7;
  const day = days <= 0 ? 'azi' : days === 1 ? 'ieri' : !dated ? weekday : `${String(a.d).padStart(2, '0')}.${String(a.m).padStart(2, '0')}`;
  return { day, hm: a.hm, dated };
}

/**
 * Whether a kept record may be shown now: a picture, taken in the past, not older than the limit.
 * @param {any} record @param {number} now
 */
export function keptUsable(record, now) {
  if (!record || typeof record !== 'object') return false;
  const at = Number(record.at);
  if (!Number.isFinite(at) || at > now + 60000 || now - at > KEEP_MAX_AGE_MS) return false;
  return Boolean(record.blob) && Number(record.w) > 0 && Number(record.h) > 0;
}

/**
 * @template T
 * @param {(done: (value: T) => void) => void} body
 * @param {T} fallback
 * @returns {Promise<T>}
 */
function guarded(body, fallback) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (/** @type {T} */ value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    const timer = setTimeout(() => done(fallback), STORE_TIMEOUT_MS);
    try {
      body(done);
    } catch {
      done(fallback);
    }
  });
}

/** @param {any} idb @returns {Promise<any|null>} the open database, or null */
function openStore(idb) {
  return guarded((done) => {
    if (!idb || typeof idb.open !== 'function') { done(null); return; }
    const request = idb.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      try {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
      } catch { /* the open's error handler answers */ }
    };
    request.onsuccess = () => done(request.result);
    request.onerror = () => done(null);
    request.onblocked = () => done(null);
  }, null);
}

/**
 * The frame kept by an earlier visit, or null.
 * @param {any} [idb] the browser's indexedDB (injected for the tests)
 * @returns {Promise<{blob: Blob, at: number, w: number, h: number}|null>}
 */
export async function readKept(idb) {
  let db = null;
  try {
    db = await openStore(idb);
    if (!db) return null;
    const store = db;
    return await guarded((done) => {
      const request = store.transaction(STORE, 'readonly').objectStore(STORE).get(KEY);
      request.onsuccess = () => done(request.result || null);
      request.onerror = () => done(null);
    }, null);
  } catch {
    return null;
  } finally {
    try { if (db) db.close(); } catch { /* */ }
  }
}

/**
 * Keeps a frame for the next entry, replacing the one kept before.
 * @param {any} idb @param {{blob: Blob, at: number, w: number, h: number}} record
 * @returns {Promise<boolean>} whether it was stored
 */
export async function writeKept(idb, record) {
  let db = null;
  try {
    db = await openStore(idb);
    if (!db) return false;
    const store = db;
    return await guarded((done) => {
      const tx = store.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put({ blob: record.blob, at: record.at, w: record.w, h: record.h }, KEY);
      tx.oncomplete = () => done(true);
      tx.onerror = () => done(false);
      tx.onabort = () => done(false);
    }, false);
  } catch {
    return false;
  } finally {
    try { if (db) db.close(); } catch { /* */ }
  }
}

/** The browser's indexedDB, or null where reading it throws. */
export function browserStore() {
  try {
    return typeof indexedDB === 'undefined' ? null : indexedDB;
  } catch {
    return null;
  }
}
