/**
 * THE FILM'S OWN FRAME, FOR THE TOAST THAT SAYS IT WAS RENDERED.
 *
 * The page may not play a film through a `blob:` URL (the Content-Security-Policy's media-src
 * falls back to 'self'), and the backend keeps no poster image. So the frame is decoded the way
 * a player would, without a <video>: the page reads the start of the rendered MP4 (the studio's
 * encoder writes `+faststart`, so the index is at the front), finds one key frame in it, and
 * hands those bytes to the browser's own decoder (WebCodecs). Nothing is guessed: the picture is
 * a frame of the file the render event names, or there is no picture.
 *
 * The parser is pure and has a test against a real H.264 file; the decode needs a browser.
 */

/** Boxes that only hold other boxes, on the path to a video track's sample tables. */
const CONTAINERS = new Set(['moov', 'trak', 'mdia', 'minf', 'stbl', 'edts', 'dinf']);

/** The largest prefix of a film the page will read to find its first frame. */
export const POSTER_MAX_BYTES = 24 * 1024 * 1024;

/** How far into the film the poster is taken, as a share of its frames (past any fade-in). */
export const POSTER_AT = 0.2;

/**
 * Where the render bay samples a film for its frame (W10): five places across it, each the key
 * frame at or before that share. The frame at POSTER_AT alone was nearly black on the Owner's
 * newest film (two small lights on black, luma 42 of 255), so the building's one picture read
 * as «no signal». The film is not filtered or brightened: one of its own frames is chosen.
 */
export const POSTER_SAMPLES = [0.1, 0.3, 0.5, 0.7, 0.9];

/**
 * A frame reads as a picture, not a flat field, when its light varies across it at least this
 * much: the spread of Rec. 709 luma (0-255) between the means of a 4x7 grid of blocks, so a fine
 * texture does not count and a shape does. Measured on the Owner's newest film (ffmpeg, the six
 * key frames): the page of notes 44, the two lights 27, the flare 38, the spiral 21, and the
 * two closing fields of warm stripes 4.5 and 4.9 — the brightest frames in it (luma 163), and
 * nothing to look at at the size of a wall screen.
 */
export const POSTER_MIN_DETAIL = 12;

/**
 * The frame to keep: the brightest one that is a picture; the brightest of all when none is.
 * @param {Array<{mean: number, detail: number}|null>} stats one per decoded frame (null: not decoded)
 * @param {number} [minDetail]
 * @returns {number} the index of the frame kept, -1 when none was decoded
 */
export function pickBrightest(stats, minDetail = POSTER_MIN_DETAIL) {
  let best = -1;
  let bestAny = -1;
  (stats || []).forEach((s, i) => {
    if (!s || !Number.isFinite(s.mean)) return;
    if (bestAny < 0 || s.mean > /** @type {any} */ (stats[bestAny]).mean) bestAny = i;
    if (s.detail >= minDetail && (best < 0 || s.mean > /** @type {any} */ (stats[best]).mean)) best = i;
  });
  return best >= 0 ? best : bestAny;
}

/**
 * The mean Rec. 709 luma of an RGBA image (0-255), and its detail: the spread between the means
 * of a grid of blocks (4 across, 7 down for a 9:16 frame).
 * @param {Uint8ClampedArray|Uint8Array|number[]} rgba @param {number} width @param {number} height
 * @param {[number, number]} [grid]
 */
export function lumaStats(rgba, width, height, grid = [4, 7]) {
  const [gx, gy] = grid;
  const sums = new Array(gx * gy).fill(0);
  const counts = new Array(gx * gy).fill(0);
  let total = 0;
  let n = 0;
  for (let y = 0; y < height; y += 1) {
    const by = Math.min(gy - 1, Math.floor((y * gy) / height));
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4;
      if (i + 2 >= rgba.length) break;
      const l = 0.2126 * rgba[i] + 0.7152 * rgba[i + 1] + 0.0722 * rgba[i + 2];
      const b = by * gx + Math.min(gx - 1, Math.floor((x * gx) / width));
      sums[b] += l;
      counts[b] += 1;
      total += l;
      n += 1;
    }
  }
  if (!n) return { mean: NaN, detail: NaN };
  const means = sums.map((v, i) => (counts[i] ? v / counts[i] : NaN)).filter(Number.isFinite);
  const m = means.reduce((a, v) => a + v, 0) / means.length;
  const detail = Math.sqrt(means.reduce((a, v) => a + (v - m) ** 2, 0) / means.length);
  return { mean: total / n, detail };
}

/**
 * The distinct key frames at the given shares of a film, in the order they appear.
 * @param {ArrayBuffer|Uint8Array} input @param {number[]} shares
 */
export function keyFramesAt(input, shares) {
  /** @type {NonNullable<ReturnType<typeof keyFrame>>[]} */
  const found = [];
  for (const share of shares) {
    const frame = keyFrame(input, share);
    if (frame && !found.some((f) => f.sample === frame.sample)) found.push(frame);
  }
  return found.sort((a, b) => a.sample - b.sample);
}

/**
 * @param {DataView} view
 * @param {number} at
 * @returns {string}
 */
function fourcc(view, at) {
  return String.fromCharCode(view.getUint8(at), view.getUint8(at + 1), view.getUint8(at + 2), view.getUint8(at + 3));
}

/**
 * The boxes between `start` and `end`, each with where its payload begins. A box that runs past
 * the bytes read so far is reported with `complete: false`.
 *
 * @param {DataView} view
 * @param {number} start
 * @param {number} end
 * @returns {Array<{type: string, start: number, body: number, end: number, complete: boolean}>}
 */
export function boxes(view, start, end) {
  const out = [];
  let at = start;
  while (at + 8 <= end) {
    let size = view.getUint32(at);
    const type = fourcc(view, at + 4);
    let body = at + 8;
    if (size === 1) {
      if (at + 16 > end) break;
      size = Number(view.getBigUint64(at + 8));
      body = at + 16;
    } else if (size === 0) {
      size = view.byteLength - at;
    }
    if (size < body - at) break;
    const boxEnd = at + size;
    out.push({ type, start: at, body, end: Math.min(boxEnd, view.byteLength), complete: boxEnd <= view.byteLength });
    at = boxEnd;
  }
  return out;
}

/**
 * Where the `moov` box is, when enough of the file has been read to say.
 * @param {DataView} view
 * @returns {{found: boolean, complete: boolean, end: number}}
 */
export function locateMoov(view) {
  for (const box of boxes(view, 0, view.byteLength)) {
    if (box.type === 'moov') return { found: true, complete: box.complete, end: box.start + (box.complete ? box.end - box.start : 0) };
    if (!box.complete) break;
  }
  return { found: false, complete: false, end: 0 };
}

/**
 * The first video track's decoder configuration and one key frame's place in the file.
 *
 * @param {ArrayBuffer|Uint8Array} input the file's first bytes, at least the whole `moov`
 * @param {number} [at] which key frame, as a share of the track's frames (0 = the first)
 * @returns {{codec: string, description: Uint8Array, width: number, height: number,
 *            sample: number, samples: number, offset: number, size: number, timescale: number}|null}
 */
export function keyFrame(input, at = 0) {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const moov = boxes(view, 0, view.byteLength).find((b) => b.type === 'moov');
  if (!moov || !moov.complete) return null;
  for (const trak of boxes(view, moov.body, moov.end).filter((b) => b.type === 'trak')) {
    const found = /** @type {Record<string, {start: number, body: number, end: number}>} */ ({});
    const walk = (/** @type {number} */ start, /** @type {number} */ end) => {
      for (const box of boxes(view, start, end)) {
        if (!(box.type in found)) found[box.type] = box;
        if (CONTAINERS.has(box.type)) walk(box.body, box.end);
      }
    };
    walk(trak.body, trak.end);
    const hdlr = found.hdlr;
    if (!hdlr || fourcc(view, hdlr.body + 8) !== 'vide') continue;
    const stsd = found.stsd;
    if (!stsd) continue;
    // The first sample entry: an 'avc1' (or 'avc3') VisualSampleEntry, 78 bytes of fields, then
    // its children, among which the avcC the decoder is configured with.
    const entry = boxes(view, stsd.body + 8, stsd.end)[0];
    if (!entry || (entry.type !== 'avc1' && entry.type !== 'avc3')) return null;
    const width = view.getUint16(entry.body + 24);
    const height = view.getUint16(entry.body + 26);
    const avcC = boxes(view, entry.body + 78, entry.end).find((b) => b.type === 'avcC');
    if (!avcC) return null;
    const hex = (/** @type {number} */ n) => n.toString(16).padStart(2, '0');
    const codec = `avc1.${hex(view.getUint8(avcC.body + 1))}${hex(view.getUint8(avcC.body + 2))}${hex(view.getUint8(avcC.body + 3))}`;
    const description = bytes.slice(avcC.body, avcC.end);
    const mdhd = found.mdhd;
    const timescale = mdhd ? view.getUint32(mdhd.body + (view.getUint8(mdhd.body) === 1 ? 20 : 12)) : 0;
    // Sample sizes.
    const stsz = found.stsz;
    if (!stsz) return null;
    const fixed = view.getUint32(stsz.body + 4);
    const samples = view.getUint32(stsz.body + 8);
    const sizeOf = (/** @type {number} */ n) => (fixed ? fixed : view.getUint32(stsz.body + 12 + (n - 1) * 4));
    // Chunk offsets (32- or 64-bit).
    const stco = found.stco || found.co64;
    if (!stco || !samples) return null;
    const wide = !found.stco;
    const chunks = view.getUint32(stco.body + 4);
    const chunkOffset = (/** @type {number} */ c) => (wide ? Number(view.getBigUint64(stco.body + 8 + (c - 1) * 8)) : view.getUint32(stco.body + 8 + (c - 1) * 4));
    // Samples per chunk, as runs.
    const stsc = found.stsc;
    if (!stsc) return null;
    const runs = [];
    const runCount = view.getUint32(stsc.body + 4);
    for (let i = 0; i < runCount; i += 1) {
      const base = stsc.body + 8 + i * 12;
      runs.push({ first: view.getUint32(base), per: view.getUint32(base + 4) });
    }
    // Key frames (no stss: every sample is one).
    const stss = found.stss;
    const keys = [];
    if (stss) {
      const n = view.getUint32(stss.body + 4);
      for (let i = 0; i < n; i += 1) keys.push(view.getUint32(stss.body + 8 + i * 4));
    }
    const target = Math.max(1, Math.min(samples, Math.round(at * samples) || 1));
    let sample = 1;
    if (keys.length) {
      // The last key frame at or before the target, so the poster is a frame that decodes alone.
      sample = keys[0];
      for (const k of keys) if (k <= target) sample = k;
    } else {
      sample = target;
    }
    // Walk the chunks to the sample.
    let first = 1;
    for (let c = 1; c <= chunks; c += 1) {
      let per = runs.length ? runs[0].per : 1;
      for (const run of runs) if (run.first <= c) per = run.per;
      if (sample < first + per) {
        let offset = chunkOffset(c);
        for (let s = first; s < sample; s += 1) offset += sizeOf(s);
        return { codec, description, width, height, sample, samples, offset, size: sizeOf(sample), timescale };
      }
      first += per;
    }
    return null;
  }
  return null;
}

/**
 * Reads a response body until `enough(bytes)` says it has what it needs, then stops reading.
 * @param {ReadableStreamDefaultReader<Uint8Array>} reader
 * @param {(bytes: Uint8Array) => boolean} enough
 * @param {number} max
 */
async function readUntil(reader, enough, max = POSTER_MAX_BYTES) {
  // One buffer that doubles when it is full, so a few megabytes read in 64 KB pieces are copied
  // a handful of times rather than once per piece.
  let buffer = new Uint8Array(256 * 1024);
  let length = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (value && value.byteLength) {
      if (length + value.byteLength > buffer.byteLength) {
        let size = buffer.byteLength;
        while (size < length + value.byteLength) size *= 2;
        const grown = new Uint8Array(size);
        grown.set(buffer.subarray(0, length));
        buffer = grown;
      }
      buffer.set(value, length);
      length += value.byteLength;
      if (enough(buffer.subarray(0, length))) return buffer.subarray(0, length);
    }
    if (done || length >= max) return buffer.subarray(0, length);
  }
}

/**
 * Decodes one frame of a rendered film into a small canvas. With `samples`, the key frames at
 * those shares are decoded (one read of the file, once per film) and the brightest one that is a
 * picture is kept (pickBrightest); without, the frame at POSTER_AT.
 *
 * @param {{url: string, token: string, width?: number, height?: number, timeoutMs?: number, samples?: number[], scale?: number}} options
 * @returns {Promise<HTMLCanvasElement|null>}
 */
export async function filmPoster(options) {
  if (typeof VideoDecoder === 'undefined' || typeof EncodedVideoChunk === 'undefined') return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 2500);
  try {
    const response = await fetch(options.url, {
      headers: { Authorization: `Bearer ${options.token}` },
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok || !response.body) return null;
    const reader = response.body.getReader();
    /** @type {NonNullable<ReturnType<typeof keyFrame>>[]|null} */
    let located = null;
    const shares = options.samples && options.samples.length ? options.samples : [POSTER_AT];
    const bytes = await readUntil(reader, (buffer) => {
      const view = new DataView(buffer.buffer, buffer.byteOffset, buffer.byteLength);
      if (!located) {
        const moov = locateMoov(view);
        if (!moov.found || !moov.complete) return false;
        // Only the frames inside the most the page will read of a film.
        located = keyFramesAt(buffer, shares).filter((f) => f.offset + f.size <= POSTER_MAX_BYTES);
        if (!located.length) return true;
      }
      return buffer.byteLength >= Math.max(...located.map((f) => f.offset + f.size));
    });
    reader.cancel().catch(() => {});
    const frames = (located || []).filter((f) => bytes.byteLength >= f.offset + f.size);
    if (!frames.length) return null;
    const first = frames[0];
    const config = { codec: first.codec, description: first.description, codedWidth: first.width, codedHeight: first.height, optimizeForLatency: true };
    const support = await VideoDecoder.isConfigSupported(config);
    if (!support.supported) return null;
    const width = options.width ?? 54;
    const height = options.height ?? 96;
    const scale = options.scale ?? Math.min(2, window.devicePixelRatio || 1);
    /** @type {HTMLCanvasElement[]} */
    const canvases = [];
    /** @type {Array<{mean: number, detail: number}|null>} */
    const stats = [];
    await new Promise((resolve) => {
      const decoder = new VideoDecoder({
        output: (videoFrame) => {
          const canvas = document.createElement('canvas');
          canvas.width = Math.round(width * scale);
          canvas.height = Math.round(height * scale);
          canvas.setAttribute('width', String(canvas.width));
          canvas.setAttribute('height', String(canvas.height));
          const ctx = canvas.getContext('2d', { willReadFrequently: frames.length > 1 });
          if (ctx) {
            // Cover: the film is 9:16, and so is the canvas.
            const ratio = Math.max(canvas.width / videoFrame.displayWidth, canvas.height / videoFrame.displayHeight);
            const w = videoFrame.displayWidth * ratio;
            const h = videoFrame.displayHeight * ratio;
            ctx.drawImage(videoFrame, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h);
          }
          videoFrame.close();
          canvases.push(canvas);
          if (ctx && frames.length > 1) {
            stats.push(lumaStats(ctx.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height));
          } else {
            stats.push({ mean: 0, detail: 0 });
          }
        },
        error: () => resolve(false),
      });
      decoder.configure(config);
      frames.forEach((frame, i) => {
        decoder.decode(new EncodedVideoChunk({ type: 'key', timestamp: i * 1000, data: bytes.subarray(frame.offset, frame.offset + frame.size) }));
      });
      decoder.flush().then(() => { decoder.close(); resolve(true); }).catch(() => resolve(false));
    });
    const keep = pickBrightest(stats);
    const chosen = keep >= 0 ? canvases[keep] : null;
    if (chosen) {
      chosen.dataset.sample = String(frames[keep] ? frames[keep].sample : '');
      chosen.dataset.luma = stats[keep] ? String(Math.round(stats[keep].mean)) : '';
      chosen.dataset.sampled = String(frames.length);
      chosen.dataset.detail = stats[keep] ? String(Math.round(stats[keep].detail)) : '';
      chosen.dataset.all = stats.map((s) => (s ? `${Math.round(s.mean)}/${Math.round(s.detail)}` : '-')).join(' ');
    }
    return chosen;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
