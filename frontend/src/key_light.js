/**
 * THE PAGE'S KEY LIGHT, TAKEN FROM THE PICTURE IT FRAMES.
 *
 * The cool wash at the top of the page (style.css, body::before, --key-cool) used to be one fixed
 * blue whatever the render showed. It is now the colour of the sky in the frame the visitor is
 * actually looking at: the Unreal stream's kept frame while the stream plays (hq_stream.js copies
 * one every 2 s) or the page's own renderer when it does not. Every 2 s the top band of that frame
 * is reduced to a few pixels, averaged, softened and clamped, and written to --key-cool.
 *
 * THE CLAMP. The wash lies on the page ground under the smallest text that stands on that ground
 * (--ink-3, the footer and the captions). Whatever the sky does, the colour is held to a soft,
 * darkish tint and its strength is lowered until that text still reads at 4.5:1 over the ground
 * the wash makes at its brightest point. A white noon sky cannot wash the page out, and a black
 * night cannot turn the light off: there is a floor and a ceiling.
 */

/** The page ground (--bg) and the faintest text that stands on it (--ink-3). */
export const GROUND = [5, 8, 14];
export const FAINT_INK = [138, 152, 178];
/** How strong the wash may be at its brightest point, and the least it keeps. */
export const KEY_ALPHA = { max: 0.2, min: 0.08 };
/** The contrast the faintest text keeps over the lit ground. */
export const KEY_MIN_RATIO = 4.5;
/** How often the frame is read (the stream's still is copied at the same rate). */
export const KEY_SAMPLE_MS = 2000;
/** The share of the frame's height read as "sky": the top band. */
export const KEY_BAND = 0.3;
/** The fixed light the page had before, and keeps when there is no frame to read. */
export const KEY_DEFAULT = { r: 66, g: 104, b: 168, a: 0.16 };

/** @param {number} c 0..255 */
function channel(c) {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** WCAG relative luminance. @param {number[]} rgb */
export function luminance(rgb) {
  return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
}

/** WCAG contrast ratio of two colours. @param {number[]} a @param {number[]} b */
export function contrastRatio(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/**
 * The mean colour of RGBA pixels, skipping transparent ones.
 * @param {ArrayLike<number>} data RGBA bytes
 * @returns {number[]|null}
 */
export function meanColour(data) {
  let r = 0;
  let g = 0;
  let b = 0;
  let n = 0;
  for (let i = 0; i + 3 < data.length; i += 4) {
    if (data[i + 3] < 16) continue;
    r += data[i];
    g += data[i + 1];
    b += data[i + 2];
    n += 1;
  }
  return n ? [r / n, g / n, b / n] : null;
}

/** @param {number[]} rgb 0..255 @returns {number[]} h 0..360, s 0..1, l 0..1 */
function toHsl([r, g, b]) {
  const [R, G, B] = [r / 255, g / 255, b / 255];
  const max = Math.max(R, G, B);
  const min = Math.min(R, G, B);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h = 0;
  if (max === R) h = (G - B) / d + (G < B ? 6 : 0);
  else if (max === G) h = (B - R) / d + 2;
  else h = (R - G) / d + 4;
  return [h * 60, s, l];
}

/** @param {number[]} hsl @returns {number[]} */
function toRgb([h, s, l]) {
  const k = (/** @type {number} */ n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (/** @type {number} */ n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)].map((v) => Math.round(v * 255));
}

/**
 * The key light for a sampled sky colour: its hue kept, its saturation and lightness held inside
 * a soft band, and its strength lowered until the faintest text on the page ground still reads.
 * @param {number[]|null} sky mean colour of the frame's top band, or null when there is none
 * @returns {{r:number, g:number, b:number, a:number}}
 */
export function keyLight(sky) {
  if (!sky) return { ...KEY_DEFAULT };
  const [h, s, l] = toHsl(sky);
  // a grey sky gives a grey light; nothing gets more colourful than a clear dusk
  const rgb = toRgb([h, Math.min(0.62, s), Math.max(0.3, Math.min(0.56, l))]);
  // brighter skies give a slightly stronger wash, within the band
  let a = KEY_ALPHA.min + (KEY_ALPHA.max - KEY_ALPHA.min) * Math.max(0, Math.min(1, l / 0.7));
  const lit = (/** @type {number} */ alpha) => GROUND.map((c, i) => c + (rgb[i] - c) * alpha);
  while (a > 0.01 && contrastRatio(FAINT_INK, lit(a)) < KEY_MIN_RATIO) a -= 0.01;
  return { r: rgb[0], g: rgb[1], b: rgb[2], a: Math.round(a * 1000) / 1000 };
}

/** The CSS value, quantised so a frame that barely changed does not repaint the page. */
export function keyLightCss(light) {
  const q = (/** @type {number} */ v) => Math.round(v / 4) * 4;
  return `rgba(${q(light.r)}, ${q(light.g)}, ${q(light.b)}, ${Math.round(light.a * 100) / 100})`;
}

/**
 * W30: a small bitmap's RGBA bytes, copied out asynchronously through a VideoFrame (WebCodecs), so
 * the main thread never waits on the GPU for them. Null where the browser cannot (no VideoFrame,
 * or it refuses the conversion): the caller then reads them through a canvas, as before.
 * @param {ImageBitmap} bitmap
 * @returns {Promise<Uint8Array|null>}
 */
export async function readAsync(bitmap) {
  const Frame = /** @type {any} */ (globalThis).VideoFrame;
  if (typeof Frame !== 'function') return null;
  let frame = null;
  try {
    frame = new Frame(bitmap, { timestamp: 0 });
    const options = { format: 'RGBA' };
    const bytes = new Uint8Array(frame.allocationSize(options));
    await frame.copyTo(bytes, options);
    return bytes;
  } catch {
    return null;
  } finally {
    if (frame) frame.close();
  }
}

/**
 * Reads the frame every KEY_SAMPLE_MS and writes the light. The reduction happens off the main
 * thread (createImageBitmap resizes the band to 8x2); only 64 bytes are read back.
 */
export class KeyLight {
  /**
   * @param {{target: HTMLElement, source: () => (HTMLCanvasElement|null), property?: string}} options
   */
  constructor(options) {
    this.target = options.target;
    this.source = options.source;
    this.property = options.property || '--key-cool';
    this.timer = 0;
    this.busy = false;
    this.value = '';
    /** @type {HTMLCanvasElement|null} */
    this.small = null;
  }

  start() {
    if (this.timer || typeof window === 'undefined') return;
    this.timer = window.setInterval(() => this.sample(), KEY_SAMPLE_MS);
    this.sample();
  }

  stop() {
    window.clearInterval(this.timer);
    this.timer = 0;
    this.write('');
  }

  /** @param {string} value an rgba() or '' to hand the token back to the stylesheet */
  write(value) {
    if (value === this.value) return;
    this.value = value;
    if (value) this.target.style.setProperty(this.property, value);
    else this.target.style.removeProperty(this.property);
  }

  async sample() {
    if (this.busy || typeof createImageBitmap !== 'function') return;
    const frame = this.source();
    if (!frame || !frame.width || !frame.height) return;
    this.busy = true;
    try {
      const band = Math.max(1, Math.round(frame.height * KEY_BAND));
      const bitmap = await createImageBitmap(frame, 0, 0, frame.width, band, { resizeWidth: 8, resizeHeight: 2, resizeQuality: 'medium' });
      // W30: the 64 bytes are read back without the main thread waiting for the GPU. Drawing the
      // bitmap into a canvas and asking it for its pixels made the page wait 22-33 ms for the GPU
      // every two seconds (measured at rest, 1920x1080); a VideoFrame's copy is asynchronous.
      const pixels = await readAsync(bitmap);
      if (pixels) {
        bitmap.close();
        if (!this.timer) return;
        this.write(keyLightCss(keyLight(meanColour(pixels))));
        return;
      }
      if (!this.small) {
        this.small = document.createElement('canvas');
        this.small.width = 8;
        this.small.height = 2;
      }
      const context = this.small.getContext('2d', { willReadFrequently: true });
      if (!context) return;
      context.clearRect(0, 0, 8, 2);
      context.drawImage(bitmap, 0, 0);
      bitmap.close();
      if (!this.timer) return;
      this.write(keyLightCss(keyLight(meanColour(context.getImageData(0, 0, 8, 2).data))));
    } catch {
      // a frame that cannot be read (a stream without a picture yet) leaves the light as it was
    } finally {
      this.busy = false;
    }
  }
}
