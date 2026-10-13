// PAGE_SETTINGS_ERRORS (PAGE-17): bounded media memory for the page. The shooting sheet used to
// keep every still it showed for the whole session, and every clip or film played left its object
// URL alive. MediaCache is a least-recently-used map that revokes what it lets go; ObjectUrls
// tracks the clips of one view so they are revoked together when the view goes.

/** How many pictures the shooting sheet keeps: a film's stills and their candidates, twice over. */
export const PICTURE_CAPACITY = 60;

/** Frees an object URL; a data: URL holds nothing to free. @param {unknown} url */
export function revokeUrl(url) {
  if (typeof url === 'string' && url.startsWith('blob:') && typeof URL.revokeObjectURL === 'function') {
    URL.revokeObjectURL(url);
  }
}

export class MediaCache {
  /**
   * @param {number} [capacity]
   * @param {(url: string) => void} [revoke] called for every URL the cache lets go
   */
  constructor(capacity = PICTURE_CAPACITY, revoke = revokeUrl) {
    this.capacity = Math.max(1, Math.floor(capacity));
    this.revoke = revoke;
    /** @type {Map<string, string>} insertion order is recency: the first key is the oldest */
    this.entries = new Map();
  }

  get size() {
    return this.entries.size;
  }

  /** The URL kept for a key, marked as the newest. @param {string} key */
  get(key) {
    const url = this.entries.get(key);
    if (url === undefined) return undefined;
    this.entries.delete(key);
    this.entries.set(key, url);
    return url;
  }

  /** @param {string} key @param {string} url */
  set(key, url) {
    const old = this.entries.get(key);
    if (old !== undefined) {
      this.entries.delete(key);
      if (old !== url) this.revoke(old);
    }
    this.entries.set(key, url);
    while (this.entries.size > this.capacity) {
      const [oldestKey, oldestUrl] = this.entries.entries().next().value;
      this.entries.delete(oldestKey);
      this.revoke(oldestUrl);
    }
  }

  clear() {
    for (const url of this.entries.values()) this.revoke(url);
    this.entries.clear();
  }
}

export class ObjectUrls {
  /** @param {(url: string) => void} [revoke] */
  constructor(revoke = revokeUrl) {
    this.revoke = revoke;
    /** @type {string[]} */
    this.urls = [];
  }

  get size() {
    return this.urls.length;
  }

  /** @param {string} url @returns {string} the same URL, to assign where it plays */
  add(url) {
    this.urls.push(url);
    return url;
  }

  revokeAll() {
    for (const url of this.urls.splice(0)) this.revoke(url);
  }
}
