/**
 * The headquarters art, as built in Blender (art-source/blender/hq) and served from /assets/hq:
 * the anchor manifest, the plate layers (night and day), the employees' and pedestrians' sprite
 * sheets, the vehicle catalogue, the painted cloud layers of the sky (art-source/sky) and the
 * random-event configuration.
 *
 * The daytime plates are loaded only when the sun is up or about to be, so a night visit does not
 * pay for pictures it will not show.
 */

const BASE = '/assets/hq';

/** @param {string} src @returns {Promise<HTMLImageElement|null>} */
export function loadImage(src) {
  return new Promise((resolve) => {
    if (typeof Image === 'undefined') {
      resolve(null);
      return;
    }
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

/** @param {string} path */
async function readJson(path) {
  try {
    const response = await fetch(`${BASE}/${path}`);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export class HQAssets {
  constructor() {
    /** @type {any} */
    this.manifest = null;
    /** @type {any} */
    this.plates = null;
    /** @type {any} */
    this.characters = null;
    /** @type {any} */
    this.pedestrians = null;
    /** @type {any} */
    this.vehicles = null;
    /** @type {any} */
    this.events = null;
    /** @type {Record<string, Record<string, {img: HTMLImageElement, x:number, y:number, w:number, h:number}>>} */
    this.layers = { night: {}, day: {} };
    /** @type {Map<string, HTMLImageElement>} */
    this.sheets = new Map();
    /** @type {Map<string, Promise<void>>} */
    this.variantLoads = new Map();
    this.ready = false;
  }

  async load() {
    const [manifest, plates, characters, pedestrians, vehicles, events] = await Promise.all([
      readJson('manifest.json'),
      readJson('plates/plates.json'),
      readJson('characters/characters.json'),
      readJson('characters/pedestrians.json'),
      readJson('vehicles/vehicles.json'),
      readJson('world_events.json'),
    ]);
    Object.assign(this, { manifest, plates, characters, pedestrians, vehicles, events });
    if (!manifest || !plates) return false;
    /** @type {Promise<void>[]} */
    const jobs = [this.loadVariant('night')];
    for (const [key, entry] of Object.entries(characters?.characters || {})) jobs.push(this.loadSheet(`char:${key}`, `characters/${entry.sheet}`));
    for (const [key, entry] of Object.entries(pedestrians?.characters || {})) jobs.push(this.loadSheet(`ped:${key}`, `characters/${entry.sheet}`));
    for (const [kind, entry] of Object.entries(vehicles?.vehicles || {})) jobs.push(this.loadSheet(`veh:${kind}`, `vehicles/${entry.sheet}`));
    for (const look of ['dusk', 'day', 'night']) jobs.push(this.loadSheet(`sky:${look}`, `sky/clouds_${look}.webp`));
    await Promise.all(jobs);
    this.ready = true;
    return true;
  }

  /** @param {string} key @param {string} path */
  async loadSheet(key, path) {
    const img = await loadImage(`${BASE}/${path}`);
    if (img) this.sheets.set(key, img);
  }

  /** @param {'night'|'day'} variant */
  loadVariant(variant) {
    const existing = this.variantLoads.get(variant);
    if (existing) return existing;
    const entries = Object.entries(this.plates?.variants?.[variant] || {});
    const job = Promise.all(
      entries.map(async ([layer, info]) => {
        const img = await loadImage(`${BASE}/plates/${info.file}`);
        if (img) this.layers[variant][layer] = { img, x: info.x, y: info.y, w: info.w, h: info.h };
      }),
    ).then(() => undefined);
    this.variantLoads.set(variant, job);
    return job;
  }

  /** @param {'night'|'day'} variant @param {string} layer */
  layer(variant, layer) {
    return this.layers[variant]?.[layer] || null;
  }

  /** @param {string} key */
  sheet(key) {
    return this.sheets.get(key) || null;
  }
}
