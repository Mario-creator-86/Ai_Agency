import { drawerDefaults, drawerInsets, frameFloor, railCount, resolveDrawers } from './game_frame.js';

/**
 * THE TWO GLASS DRAWERS OF THE GAME FRAME.
 *
 * On a screen wide and tall enough (FRAME_QUERY, the same numbers as the stylesheet's frame
 * block), the render is the whole first viewport and three panels lie over its edges: the live
 * register on the left, governance with the approvals and the module status on the right. Each
 * side closes to a slim rail that keeps its count («70 de intrări», «NICIUNA»), and opens again
 * from it. A drawer the visitor never touched opens only where the building still fits beside it
 * (game_frame.js drawerDefaults); one they opened or closed stays that way on this browser.
 *
 * The seven rooms go up into the masthead in the frame, where they read as the studio's own menu,
 * and come back to the console under the render on a narrow screen.
 *
 * Nothing here decides anything about the studio. The drawers show and hide panels; every word and
 * count in them is the panel's own.
 */

/** The frame's media query. Kept equal to the stylesheet's frame block (tests/game_frame_css.test.js). */
export const FRAME_QUERY = '(min-width: 1051px) and (min-height: 600px)';
const STORE_KEY = 'amn.drawers';

/** @param {string} id */
function byId(id) {
  return /** @type {HTMLElement|null} */ (document.getElementById(id));
}

function readStored() {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

/** @param {any} value */
function writeStored(value) {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(value));
  } catch {
    // a private window or blocked storage: the choice holds for this visit only
  }
}

export class Drawers {
  /**
   * @param {{
   *   onInsets?: (insets: import('./game_frame.js').Insets, options: {glide: boolean, floor?: import('./game_frame.js').Insets}) => void,
   *   world?: () => {worldW: number, worldH: number, focus: import('./game_frame.js').Rect},
   * }} [options]
   */
  constructor(options = {}) {
    this.onInsets = options.onInsets || (() => {});
    this.world = options.world || (() => ({ worldW: 1600, worldH: 840, focus: { x: 415, y: 10, width: 937, height: 665 } }));
    this.media = typeof window.matchMedia === 'function' ? window.matchMedia(FRAME_QUERY) : null;
    this.root = document.documentElement;
    this.register = byId('register-panel');
    this.governance = byId('governance-panel');
    this.modules = byId('modules-panel');
    this.readout = byId('studio-readout');
    this.registerRail = /** @type {HTMLButtonElement|null} */ (byId('register-rail'));
    this.sideRail = /** @type {HTMLButtonElement|null} */ (byId('side-rail'));
    this.registerClose = /** @type {HTMLButtonElement|null} */ (byId('register-close'));
    this.sideClose = /** @type {HTMLButtonElement|null} */ (byId('side-close'));
    this.rooms = /** @type {HTMLElement|null} */ (document.querySelector('.toolbar-modules'));
    this.roomsHome = this.rooms ? this.rooms.parentElement : null;
    this.roomsTop = byId('topbar-rooms');
    /** What the visitor chose on this browser. @type {{register?: boolean, side?: boolean}} */
    this.stored = readStored() || {};
    this.open = { register: true, side: true };
    this.framed = false;
    this.started = false;
    /** @type {{registerW: number, sideW: number, railW: number, hudTop: number}|null} */
    this._widthsNow = null;
    this._widthsKey = '';
  }

  start() {
    if (this.started) return;
    this.started = true;
    this.registerRail?.addEventListener('click', () => this.set('register', true, { focus: true }));
    this.sideRail?.addEventListener('click', () => this.set('side', true, { focus: true }));
    this.registerClose?.addEventListener('click', () => this.set('register', false, { focus: true }));
    this.sideClose?.addEventListener('click', () => this.set('side', false, { focus: true }));
    this.media?.addEventListener('change', () => this.layout());
    // The rails repeat the panels' own counts, as the panels change them.
    this._mirror('ledger-count', 'register-rail-count');
    this._mirror('approvals-count', 'side-rail-count');
    let last = '';
    window.addEventListener('resize', () => {
      const key = `${window.innerWidth}x${window.innerHeight}`;
      if (key === last) return;
      last = key;
      this.layout({ glide: false });
    }, { passive: true });
    this.layout({ glide: false });
  }

  /** Whether the page is in the game frame now. */
  isFramed() {
    return Boolean(this.media && this.media.matches);
  }

  /**
   * Lay the frame out for the screen as it is: the rooms in the masthead or in the console, the
   * drawers as the visitor left them or as the building allows.
   * @param {{glide?: boolean}} [options]
   */
  layout(options = {}) {
    this.framed = this.isFramed();
    this._placeRooms();
    if (!this.framed) {
      delete this.root.dataset.register;
      delete this.root.dataset.side;
      for (const panel of [this.register, this.governance, this.modules, this.readout]) if (panel) panel.inert = false;
      if (this.registerRail) this.registerRail.hidden = true;
      if (this.sideRail) this.sideRail.hidden = true;
      this.onInsets({ left: 0, right: 0, top: 0, bottom: 0 }, { glide: false });
      return;
    }
    this.open = resolveDrawers(this.stored, this.defaults());
    this.apply({ glide: options.glide === true });
  }

  /** Which drawers fit beside the building on this screen. */
  defaults() {
    const box = this._frameBox();
    const widths = this._widths();
    const { worldW, worldH, focus } = this.world();
    return drawerDefaults({ cw: box.width, ch: box.height, worldW, worldH, focus, ...widths });
  }

  /**
   * Open or close one drawer because the visitor asked; the choice is kept on this browser.
   * @param {'register'|'side'} which
   * @param {boolean} open
   * @param {{focus?: boolean, remember?: boolean}} [options]
   */
  set(which, open, options = {}) {
    if (!this.framed) return;
    this.open = { ...this.open, [which]: open };
    if (options.remember !== false) {
      this.stored = { ...this.stored, [which]: open };
      writeStored(this.stored);
    }
    this.apply({ glide: true });
    if (!options.focus) return;
    const target = which === 'register'
      ? (open ? this.registerClose : this.registerRail)
      : (open ? this.sideClose : this.sideRail);
    target?.focus({ preventScroll: true });
  }

  /** @param {{glide: boolean}} options */
  apply(options) {
    const { register, side } = this.open;
    this.root.dataset.register = register ? 'open' : 'closed';
    this.root.dataset.side = side ? 'open' : 'closed';
    // A closed drawer is out of the tab walk and out of what a screen reader reads; its rail is in.
    if (this.register) this.register.inert = !register;
    if (this.governance) this.governance.inert = !side;
    if (this.modules) this.modules.inert = !side;
    if (this.readout) this.readout.inert = !side;
    if (this.registerRail) {
      this.registerRail.hidden = register;
      this.registerRail.setAttribute('aria-expanded', String(register));
    }
    if (this.sideRail) {
      this.sideRail.hidden = side;
      this.sideRail.setAttribute('aria-expanded', String(side));
    }
    this.registerClose?.setAttribute('aria-expanded', String(register));
    this.sideClose?.setAttribute('aria-expanded', String(side));
    const widths = this._widths();
    // The frame always keeps its rails and the row of sky over the roof where the clock, the dock
    // and the live state stand (game_frame.js frameFloor): the camera's zoom is chosen against it.
    this.onInsets(drawerInsets(this.open, widths), { glide: options.glide, floor: frameFloor(widths) });
  }

  /** The render's box in the frame. */
  _frameBox() {
    const viewport = byId('scene-viewport');
    const rect = viewport ? viewport.getBoundingClientRect() : null;
    return rect && rect.width > 0 ? { width: rect.width, height: rect.height } : { width: window.innerWidth, height: window.innerHeight };
  }

  /** Measure the drawers' widths now, while nothing is moving (the title screen). */
  prime() {
    this._widths();
  }

  /**
   * The drawers' widths, measured once per window size: a measurement lays the page out, and the
   * first one is taken while the title is up (main.js warmOffice), not at the key.
   */
  _widths() {
    const key = `${window.innerWidth}x${window.innerHeight}`;
    if (!this._widthsNow || this._widthsKey !== key) {
      this._widthsNow = this._measureWidths();
      this._widthsKey = key;
    }
    return this._widthsNow;
  }

  /** The drawers' widths as the stylesheet lays them out (their tokens), the rail's, and the row of sky the instruments stand in. */
  _measureWidths() {
    // A token such as clamp(300px, 18.75vw, 400px) is resolved by the browser, on a probe.
    const px = (/** @type {string} */ name, /** @type {number} */ fallback) => {
      const probe = document.createElement('div');
      probe.style.position = 'absolute';
      probe.style.visibility = 'hidden';
      probe.style.width = `var(${name})`;
      document.body.append(probe);
      const width = probe.getBoundingClientRect().width;
      probe.remove();
      return width > 0 ? width : fallback;
    };
    return { registerW: px('--drawer-register', 360), sideW: px('--drawer-side', 340), railW: px('--drawer-rail', 40), hudTop: px('--hud-top', 0) };
  }

  /** The rooms: the masthead's menu in the frame, the console's second tier otherwise. */
  _placeRooms() {
    if (!this.rooms || !this.roomsHome || !this.roomsTop) return;
    const home = this.framed ? this.roomsTop : this.roomsHome;
    if (this.rooms.parentElement !== home) home.append(this.rooms);
    this.roomsTop.hidden = !this.framed;
  }

  /** @param {string} from @param {string} to */
  _mirror(from, to) {
    const source = byId(from);
    const target = byId(to);
    if (!source || !target) return;
    const copy = () => {
      target.textContent = railCount(source.textContent);
    };
    copy();
    new MutationObserver(copy).observe(source, { childList: true, characterData: true, subtree: true });
  }

  /** The gold mark asked for the approvals: the drawer that holds them opens. */
  showApprovals() {
    if (this.framed && !this.open.side) this.set('side', true);
  }

  /**
   * Requests are waiting for the Owner: the closed drawer's rail wears the gold, as the mark does.
   * @param {number} pending
   */
  setPending(pending) {
    if (this.sideRail) this.sideRail.dataset.pending = pending > 0 ? 'true' : 'false';
  }
}
