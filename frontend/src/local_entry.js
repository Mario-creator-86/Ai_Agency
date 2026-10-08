// @ts-check
/**
 * LOCAL_AUTO_LOGIN (2026-10-08). The Owner: «Te rog sa elimini pagina de logare, nu trebuie
 * momentan».
 *
 * On his own machine the studio hands this page his key (GET /api/v1/owner/local-session, answered
 * only to a loopback peer at the studio's own loopback address; backend/app/local_session.py) and
 * the page enters exactly as the form would. From anywhere else the route is a 404 and the form
 * shows as before, so remote access keeps working. The key is kept only in the page's memory, as a
 * typed one is: never in storage, a cookie or the URL.
 *
 * After a sign-out the form shows again and offers to enter without the key (an empty field and
 * «Intră în studio»); after a key the studio refuses later (401), the page tries once by itself
 * per page load, never in a loop.
 */

export const LOCAL_SESSION_URL = '/api/v1/owner/local-session';
/**
 * The header only this page's own fetch sends. The studio answers no request without it: an
 * <img>, <script>, frame, form or link of another site cannot add a header, and another origin's
 * fetch that adds one needs a CORS preflight the studio never answers.
 */
export const LOCAL_SESSION_HEADER = 'X-Studio-Local-Session';
/** Long enough for a studio busy with a film, short enough that the form is not kept waiting. */
export const LOCAL_SESSION_TIMEOUT_MS = 4000;
/** The studio refuses an Owner key shorter than this (backend/app/config.py). */
const MIN_KEY_LENGTH = 32;

/**
 * The Owner's key from the studio on this machine, or null (a 404, a network failure, a timeout,
 * an answer that is not a key).
 * @param {{ fetchImpl?: typeof fetch, timeoutMs?: number }} [options]
 * @returns {Promise<string|null>}
 */
export async function askLocalKey({ fetchImpl = globalThis.fetch, timeoutMs = LOCAL_SESSION_TIMEOUT_MS } = {}) {
  if (typeof fetchImpl !== 'function') return null;
  try {
    const signal = typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
      ? AbortSignal.timeout(timeoutMs)
      : undefined;
    const response = await fetchImpl(LOCAL_SESSION_URL, {
      method: 'GET',
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error',
      headers: { Accept: 'application/json', [LOCAL_SESSION_HEADER]: '1' },
      signal,
    });
    if (!response || !response.ok) return null;
    const body = await response.json();
    const token = body && typeof body.token === 'string' ? body.token : '';
    return token.length >= MIN_KEY_LENGTH ? token : null;
  } catch {
    return null;
  }
}

/**
 * The page's way in without the form.
 *
 * `ask` gets a key (askLocalKey); `enter(key)` is the page's one way in, the same the form uses,
 * and resolves true when the studio accepted the key; `view.waiting()` hides the form under the
 * title's waiting line; `view.form(offer)` shows the form, with the offer to enter without the key
 * when this machine handed one over at its last asking.
 */
export class LocalEntry {
  /**
   * @param {{
   *   ask: () => Promise<string|null>,
   *   enter: (key: string) => Promise<boolean>,
   *   view: { waiting: () => void, form: (offer: boolean) => void },
   * }} parts
   */
  constructor({ ask, enter, view }) {
    this.ask = ask;
    this.enter = enter;
    this.view = view;
    /** Whether this machine handed a key over at the last asking. */
    this.available = false;
    /** Whether the one automatic entry after a refused key was spent (per page load). */
    this.retriedAfterRefusal = false;
    this.running = false;
  }

  /** On page load: in without the form when this machine hands the key over. */
  start() {
    return this.attempt();
  }

  /** The Owner pressed «Intră în studio» with an empty field: his own press, not counted. */
  again() {
    return this.attempt();
  }

  /** After a sign-out: the form, offering to enter again; nothing is asked until he presses. */
  offer() {
    this.view.form(this.available);
  }

  /** After a key the studio refused: one automatic entry per page load, then the form waits. */
  async afterRefusal() {
    if (this.retriedAfterRefusal) {
      this.view.form(this.available);
      return false;
    }
    this.retriedAfterRefusal = true;
    return this.attempt();
  }

  /** @returns {Promise<boolean>} */
  async attempt() {
    if (this.running) return false;
    this.running = true;
    try {
      this.view.waiting();
      const key = await this.ask();
      this.available = Boolean(key);
      if (key && (await this.enter(key))) return true;
      this.view.form(this.available);
      return false;
    } finally {
      this.running = false;
    }
  }
}
