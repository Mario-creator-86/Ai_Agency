import { HELD_STILL_MS, STREAM_SILENT_MS, authenticateTransport, plateNote, redactingLogger, streamLayers, streamSilent } from './hq_stream_config.js';
import { KEEP_EVERY_MS, KEEP_FIRST_MS, KEEP_QUALITY, KEEP_TYPE, keptSize } from './stream_keep.js';

/**
 * THE STREAM CLIENT, LOADED ONLY WHEN THE STREAM STARTS (PAGE-20). Epic's Pixel Streaming library
 * was a static import here, so every visitor downloaded it inside the page's main chunk (777 kB),
 * the studios without Unreal included. It is now its own chunk, fetched by `loadStreamClient` when
 * main.js starts a stream the scene switched on.
 * @type {any}
 */
let client = null;

/** Whether the library has been loaded in this page. */
export function streamClientLoaded() {
  return client !== null;
}

/**
 * Loads the Pixel Streaming library once, and installs the redacting logger with it before any
 * connect. W23: the library prints the signalling URL on every connect; no line of it reaches the
 * console with the value of a `token=` (hq_stream_config.js redactKey).
 */
export async function loadStreamClient() {
  if (!client) {
    const lib = await import('@epicgames-ps/lib-pixelstreamingfrontend-ue5.8');
    const { Logger, overrideLogger } = lib;
    overrideLogger(redactingLogger(Logger));
    client = lib;
  }
  return client;
}

/** How often a frame of the live video is kept, to be shown frozen if the stream drops. */
const STILL_COPY_MS = 2000;
/**
 * How long the page waits for a picture before it asks the signalling server again. Measured
 * 2026-09-19: after a restart Unreal joined signalling 22 s after the server started, the library
 * asked for streamers for about 11 s and then stopped, and the page showed no picture for ten
 * minutes. A negotiation under way takes a few seconds, so half a minute leaves it alone.
 */
const CONNECTING_RETRY_MS = 30000;
/** Under reduced motion, how soon the first frame of a live stream is asked again when the video had none yet. */
const HELD_FIRST_MS = 250;
/**
 * How long the kept frame takes to give way to the live video once its first frame is presented
 * (W19), and how long the replay's door takes; office_scene.css runs both on --dur-slow, and
 * reduced motion makes both a cut.
 */
export const HANDOFF_MS = 480;
export const DOOR_MS = 620;

/**
 * Frames per second of the video Unreal is sending, as the browser's WebRTC statistics count
 * them, or null when the statistics do not say.
 * @param {any} aggregatedStats Pixel Streaming's AggregatedStats
 * @returns {number|null}
 */
export function inboundFrameRate(aggregatedStats) {
  const fps = aggregatedStats?.inboundVideoStats?.framesPerSecond;
  return typeof fps === 'number' && Number.isFinite(fps) && fps >= 0 ? fps : null;
}

/**
 * Shows the Unreal headquarters, streamed live over Pixel Streaming, on top of the page's own
 * renderer. The video lets clicks through to the renderer underneath, which still knows where
 * every employee sits. When the stream drops after it has shown a frame, the last frame stays,
 * frozen, with a note that the page is reconnecting; before any frame the renderer is seen. The
 * stream is retried.
 */
export class LiveStream {
  /**
   * @param {HTMLElement} viewport the element the scene is drawn in
   * @param {{signallingUrl: string, streamerId: string, retryMs: number, connectingRetryMs?: number,
   *          authMessage?: (() => string)|null}} settings
   *   `authMessage`: the backend takes the Owner's key as the signalling socket's first message and
   *   `signallingUrl` carries none (hq_stream_config.js socketAuth). Should the library's transport
   *   not take first-message auth, `firstMessageAuth` stays false and `start` connects nothing: there
   *   is no URL with the key to fall back to (SEC-02).
   * @param {{onStatus?: (status: 'connecting'|'live'|'offline') => void, onFrameRate?: (fps: number|null) => void, held?: () => boolean,
   *          onKeep?: (record: {blob: Blob, at: number, w: number, h: number}) => void, reduced?: () => boolean}} [options]
   */
  constructor(viewport, settings, options = {}) {
    if (!client) throw new Error('LiveStream: the stream client is not loaded; await loadStreamClient() first');
    const { Config, Flags, PixelStreaming } = client;
    this.viewport = viewport;
    this.settings = settings;
    this.onStatus = options.onStatus || (() => {});
    this.onFrameRate = options.onFrameRate || (() => {});
    /** A real frame of the live video, handed out rarely to be kept for the next entry (stream_keep.js). */
    this.onKeep = options.onKeep || null;
    this.reduced = options.reduced || (() => false);
    this.keepTimer = 0;
    this.handoffTimer = 0;
    this.doorTimer = 0;
    /** @type {HTMLCanvasElement|null} */
    this.keepCanvas = null;
    /** The replay's door (W19): '' or which way the layer is fading. */
    this.door = '';
    /** An earlier visit's last live frame is on the plate (showKept), named by `keptCaption`. */
    this.keptShown = false;
    this.keptCaption = '';
    /** Whether the live video has presented a frame since it last went live. */
    this.firstFrame = false;
    this.status = 'offline';
    this.retryTimer = 0;
    this.stillTimer = 0;
    this.hasStill = false;
    /** Reduced motion: the stream is seen one kept frame at a time (hq_stream_config.js HELD_STILL_MS). */
    this.held = Boolean(options.held && options.held());
    /** Whether a frame has been kept since the stream last went live. */
    this.keptLive = false;
    this.layer = document.createElement('div');
    // "fixed-size": the page's stylesheet sizes the layer; the library would otherwise write an
    // inline style, which the page's Content-Security-Policy refuses.
    this.layer.className = 'live-stream-layer fixed-size';
    this.layer.hidden = true;
    this.still = document.createElement('canvas');
    this.still.className = 'live-stream-still';
    this.still.hidden = true;
    /** W22: when the picture in `still` was taken (a copy of the video, or the kept frame's moment). */
    this.stillAt = NaN;
    this.badge = document.createElement('div');
    this.badge.className = 'live-stream-badge';
    this.badge.textContent = plateNote('reconnecting', false);
    this.badge.hidden = true;
    this.layer.append(this.still, this.badge);
    viewport.appendChild(this.layer);

    const config = new Config({
      useUrlParams: false,
      initialSettings: {
        [Flags.AutoConnect]: false,
        [Flags.AutoPlayVideo]: true,
        [Flags.StartVideoMuted]: true,
        [Flags.MouseInput]: false,
        [Flags.KeyboardInput]: false,
        [Flags.TouchInput]: false,
        [Flags.GamepadInput]: false,
        [Flags.XRControllerInput]: false,
        [Flags.MatchViewportResolution]: false,
        [Flags.HideUI]: true,
        ss: settings.signallingUrl,
      },
    });
    this.stream = new PixelStreaming(config, { videoElementParent: this.layer });
    // THE KEY OUT OF THE URL (2026-09-25): the signalling socket says it as its first message.
    // SEC-02 (2026-10-01): never in the URL, so a library whose transport the page cannot reach
    // leaves the stream unopened (main.js shows the page's renderer and STREAM_NO_SAFE_AUTH).
    this.firstMessageAuth = false;
    if (settings.authMessage) {
      const controller = /** @type {any} */ (this.stream).webRtcController;
      this.firstMessageAuth = authenticateTransport(controller && controller.transport, settings.authMessage);
    }
    /** Connects that failed since the stream was last live, and whether STREAM_SILENT_MS has passed without a picture. */
    this.failures = 0;
    this.waitedLong = false;
    this.waitTimer = 0;
    /** The page's camera, laid on the video (setView). @type {{k: number, tx: number, ty: number}|null} */
    this.view = null;
    this.stream.addEventListener('playStream', () => {
      this._setStatus('live');
      // the library may have made a new video element for this connection
      this._applyView();
      this._watchFirstFrame();
    });
    this.stream.addEventListener('webRtcConnecting', () => this._setStatus('connecting'));
    this.stream.addEventListener('webRtcDisconnected', () => this._offline());
    this.stream.addEventListener('webRtcFailed', () => this._offline());
    this.stream.addEventListener('streamerListMessage', (event) => this._pickStreamer(event));
    // The library reads the peer connection's statistics once a second; the inbound video's
    // frame rate is what Unreal is delivering to this page, and it is the figure the readout shows.
    this.stream.addEventListener('statsReceived', (event) => this._stats(event));
  }

  /** @param {any} event */
  _stats(event) {
    if (this.status !== 'live') return;
    // held, one frame is seen at a time: a frame rate would describe a motion not shown
    if (this.held) return;
    this.onFrameRate(inboundFrameRate(event?.data?.aggregatedStats));
  }

  /**
   * The visitor's system asks for reduced motion, or no longer does: the video, or one real frame
   * of it at a time.
   * @param {boolean} held
   */
  setHeld(held) {
    if (this.held === Boolean(held)) return;
    this.held = Boolean(held);
    if (this.status === 'live') this._setStatus('live');
  }

  start() {
    // without the key as the first message the relay would refuse the socket: nothing is opened
    if (!this.firstMessageAuth) return false;
    this._setStatus('connecting');
    this.stream.connect();
    return true;
  }

  /**
   * THE PAGE'S CAMERA ON THE STREAMED PICTURE. Unreal's camera is fixed; the page's zoom and pan
   * are laid on its video (and on the frozen frame) as a transform, so the visitor zooms and drags
   * what they see, and the page's hit boxes under the video keep landing on the employee under the
   * pointer (game_frame.js streamTransform).
   * @param {{k: number, tx: number, ty: number}} transform in CSS pixels
   */
  setView(transform) {
    this.view = transform;
    this._applyView();
  }

  _applyView() {
    const t = this.view;
    if (!t) return;
    const identity = Math.abs(t.k - 1) < 1e-4 && Math.abs(t.tx) < 0.05 && Math.abs(t.ty) < 0.05;
    const value = identity ? '' : `translate(${t.tx.toFixed(2)}px, ${t.ty.toFixed(2)}px) scale(${t.k.toFixed(5)})`;
    const video = /** @type {HTMLElement|null} */ (this.layer.querySelector('video'));
    for (const el of [video, this.still]) {
      if (el && el.style.transform !== value) el.style.transform = value;
    }
  }

  /** Sends the studio's own state to the Unreal scene (its agents, their desks and activity). */
  send(message) {
    if (this.status !== 'live') return false;
    return this.stream.emitUIInteraction(message);
  }

  _pickStreamer(event) {
    // The library subscribes to a streamer on its own; choosing again resubscribes and breaks the
    // negotiation already under way, so only switch when it picked a different one.
    const wanted = this.settings.streamerId;
    const ids = event?.data?.messageStreamerList?.ids || [];
    const current = this.stream.config.getSettingOption('StreamerId')?.selected;
    if (wanted && ids.includes(wanted) && current !== wanted) {
      this.stream.config.setOptionSettingValue('StreamerId', wanted);
    }
  }

  _offline() {
    if (this.status === 'live') this._copyFrame();
    // a connect that ended before a picture is a failed one; a drop from live starts the count again
    else this.failures = (this.failures || 0) + 1;
    this._setStatus('offline');
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = 0;
      if (this.status === 'offline') this.stream.reconnect();
    }, this.settings.retryMs);
  }

  /**
   * While live, keeps a frame of the video: every STILL_COPY_MS for the frozen frame an outage
   * would show, or, held, the frame that is seen, every HELD_STILL_MS (sooner until the first).
   */
  _keepFrames() {
    window.clearTimeout(this.stillTimer);
    this.stillTimer = 0;
    if (this.status !== 'live') return;
    // W20: an earlier visit's kept frame on the plate waits for the first presented frame and fades
    // off it (_firstFrame); a copy now would cut it at once and paint this visit's frame under the
    // old frame's name. Held (reduced motion), this visit's own first frame replaces it.
    if (this.keptShown && !this.held) {
      // should the first-frame callback never come, a video that has presented frames hands off
      const video = /** @type {HTMLVideoElement|null} */ (this.layer.querySelector('video'));
      const shown = video && typeof video.getVideoPlaybackQuality === 'function' ? video.getVideoPlaybackQuality().totalVideoFrames : 0;
      if (!this.firstFrame && shown > 0) this._firstFrame();
      if (this.keptShown) this.stillTimer = window.setTimeout(() => this._keepFrames(), STILL_COPY_MS);
      return;
    }
    if (this._copyFrame()) {
      this.keptLive = true;
      // held: the plate now shows this visit's own frame, not an earlier one's
      if (this.keptShown) {
        this.keptShown = false;
        this._applyLayers();
      }
    }
    const wait = !this.held ? STILL_COPY_MS : this.keptLive ? HELD_STILL_MS : HELD_FIRST_MS;
    this.stillTimer = window.setTimeout(() => this._keepFrames(), wait);
  }

  /**
   * Keeps the video's current frame in the still canvas (the video belongs to the library).
   * @returns {boolean} whether a frame was kept
   */
  _copyFrame() {
    const video = this.layer.querySelector('video');
    if (!video || !video.videoWidth || video.readyState < 2) return false;
    if (this.still.width !== video.videoWidth || this.still.height !== video.videoHeight) {
      this.still.width = video.videoWidth;
      this.still.height = video.videoHeight;
    }
    const context = this.still.getContext('2d');
    if (!context) return false;
    context.drawImage(video, 0, 0);
    this.hasStill = true;
    this.stillAt = Date.now();
    return true;
  }

  /**
   * W22: the real picture of the building the page holds now, for the replay to play over
   * (replay_still.js): the frame copied at the replay's door, a frozen or held frame, or the frame
   * an earlier visit kept; with the moment it was taken. Null when the page holds none.
   * @returns {{image: HTMLCanvasElement, at: number}|null}
   */
  replayPicture() {
    if (!(this.hasStill || this.keptShown) || !(this.still.width > 0) || !(this.still.height > 0)) return null;
    return { image: this.still, at: Number.isFinite(this.stillAt) ? this.stillAt : Date.now() };
  }

  /**
   * What the layer shows, from the status and what is kept (hq_stream_config.js streamLayers).
   * Live but before the video's first frame, an earlier visit's kept frame stays on the plate.
   */
  _applyLayers() {
    const layers = streamLayers(/** @type {'connecting'|'live'|'offline'} */ (this.status), this.hasStill, this.held, this.keptShown);
    const keptLive = this.status === 'live' && !this.held && this.keptShown;
    // the layer always covers the page's own renderer while a stream is configured
    this.layer.hidden = false;
    // the library's video is hidden by a class, not touched: the frozen copy or the note shows
    this.layer.classList.toggle('paused', this.status !== 'live');
    this.layer.classList.toggle('held', layers.held);
    this.layer.classList.toggle('waiting', layers.waiting);
    this.layer.classList.toggle('kept', layers.kept || keptLive);
    this.still.hidden = !(layers.still || keptLive || this.door === 'out');
    const note = layers.note === 'kept' || keptLive ? 'kept' : layers.note;
    // W20: while the kept frame fades off the live video its name goes with it
    this.badge.hidden = !note || Boolean(this.door) || Boolean(this.handoffTimer);
    // W21: a headquarters that has not answered for a while is said to be silent, not starting
    const silent = this.status !== 'live' && streamSilent(this.failures || 0, Boolean(this.waitedLong));
    this.layer.classList.toggle('silent', silent);
    this.badge.textContent = plateNote(/** @type {any} */ (note), silent, this.keptCaption);
  }

  /**
   * THE LAST LIVE FRAME OF AN EARLIER VISIT (W19, stream_keep.js), laid on the starting plate:
   * dimmed and named, never taken for live. Refused once this visit has a frame of its own.
   * @param {CanvasImageSource & {width: number, height: number}} image @param {string} caption
   * @param {number} [at] when it was taken (W22: the replay names the photograph's hour)
   * @returns {boolean} whether it is shown
   */
  showKept(image, caption, at = NaN) {
    if (this.hasStill || this.firstFrame || !image || !(image.width > 0) || !(image.height > 0)) return false;
    this.still.width = image.width;
    this.still.height = image.height;
    const context = this.still.getContext('2d');
    if (!context) return false;
    context.drawImage(image, 0, 0);
    this.keptShown = true;
    this.keptCaption = caption;
    this.stillAt = Number(at);
    this._applyLayers();
    return true;
  }

  /** Waits for the live video to present its first frame (the library may replace the element). */
  _watchFirstFrame() {
    const video = /** @type {HTMLVideoElement|null} */ (this.layer.querySelector('video'));
    if (!video || this.firstFrame) return;
    const seen = () => {
      if (this.status !== 'live' || this.firstFrame) return;
      this._firstFrame();
    };
    if (typeof video.requestVideoFrameCallback === 'function') video.requestVideoFrameCallback(() => seen());
    else video.addEventListener('playing', seen, { once: true });
  }

  /** The live video's first frame is on screen: the kept frame gives way, and keeping begins. */
  _firstFrame() {
    this.firstFrame = true;
    if (this.keptShown && !this.held) {
      const done = () => {
        this.handoffTimer = 0;
        this.layer.classList.remove('handoff');
        this.keptShown = false;
        this._applyLayers();
        // this visit's own frozen frame, kept from now on (W20)
        this._keepFrames();
      };
      window.clearTimeout(this.handoffTimer);
      if (this.reduced()) done();
      else {
        this.layer.classList.add('handoff');
        this.badge.hidden = true;
        this.handoffTimer = window.setTimeout(done, HANDOFF_MS + 40);
      }
    }
    this._scheduleKeep(KEEP_FIRST_MS);
  }

  /** @param {number} wait */
  _scheduleKeep(wait) {
    window.clearTimeout(this.keepTimer);
    this.keepTimer = 0;
    if (!this.onKeep) return;
    this.keepTimer = window.setTimeout(() => this._keepForNext(), wait);
  }

  /**
   * Hands out one small real frame of the live video to be kept for the next entry. Rare: once
   * KEEP_FIRST_MS after the first frame, then every KEEP_EVERY_MS; never while the page is hidden.
   */
  _keepForNext() {
    this.keepTimer = 0;
    if (this.status !== 'live' || !this.onKeep) return;
    const video = /** @type {HTMLVideoElement|null} */ (this.layer.querySelector('video'));
    const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
    const size = video && video.readyState >= 2 ? keptSize(video.videoWidth, video.videoHeight) : null;
    if (video && size && !hidden) {
      const canvas = this.keepCanvas || (this.keepCanvas = document.createElement('canvas'));
      canvas.width = size.w;
      canvas.height = size.h;
      const context = canvas.getContext('2d');
      if (context) {
        context.drawImage(video, 0, 0, size.w, size.h);
        const at = Date.now();
        const hand = this.onKeep;
        try {
          canvas.toBlob((blob) => { if (blob) hand({ blob, at, w: size.w, h: size.h }); }, KEEP_TYPE, KEEP_QUALITY);
        } catch { /* a canvas the browser will not encode keeps nothing */ }
      }
    }
    this._scheduleKeep(KEEP_EVERY_MS);
  }

  /**
   * THE REPLAY'S DOOR (W19). Into the replay: the live picture, held as a real frame of it, fades
   * into the replay underneath. Back: the live video fades in over the replay's last graded frame.
   * Under reduced motion both are a clean cut. W22: the frame copied here is also the still the
   * replay plays over (replayPicture), so the door fades one building into the same one, graded.
   * @param {'out'|'in'} way
   */
  doorway(way) {
    window.clearTimeout(this.doorTimer);
    this.doorTimer = 0;
    this.layer.classList.remove('door-out', 'door-in');
    this.door = '';
    const showing = this.status === 'live' || this.hasStill || this.keptShown;
    if (this.reduced() || !showing) {
      this._applyLayers();
      return;
    }
    if (way === 'out' && this.status === 'live' && !this.held) this._copyFrame();
    this.door = way;
    this.layer.classList.add(way === 'out' ? 'door-out' : 'door-in');
    this._applyLayers();
    this.doorTimer = window.setTimeout(() => {
      this.doorTimer = 0;
      this.door = '';
      this.layer.classList.remove('door-out', 'door-in');
      this._applyLayers();
    }, DOOR_MS + 40);
  }

  _setStatus(status) {
    // The SDK can recover first. An old fallback retry must not tear down its
    // negotiation or a live connection after the original outage has ended.
    window.clearTimeout(this.retryTimer);
    this.retryTimer = 0;
    this.status = status;
    if (status === 'connecting') {
      // Nothing streaming yet: ask again, and keep asking, until a picture arrives. A live
      // stream or an outage clears this timer on its own next status.
      const wait = this.settings.connectingRetryMs || CONNECTING_RETRY_MS;
      this.retryTimer = window.setTimeout(() => {
        this.retryTimer = 0;
        if (this.status !== 'connecting') return;
        // half a minute connecting with no picture is a failed connect too
        this.failures = (this.failures || 0) + 1;
        this.stream.reconnect();
        this._setStatus('connecting');
      }, wait);
    }
    window.clearTimeout(this.stillTimer);
    this.stillTimer = 0;
    if (status !== 'live') {
      window.clearTimeout(this.keepTimer);
      this.keepTimer = 0;
      this.firstFrame = false;
    }
    if (status === 'live') {
      this.keptLive = false;
      this.failures = 0;
      this.waitedLong = false;
      window.clearTimeout(this.waitTimer);
      this.waitTimer = 0;
      this._keepFrames();
    } else if (!this.waitTimer && !this.waitedLong) {
      // the clock of a headquarters not answering runs from the first status that is not live
      this.waitTimer = window.setTimeout(() => {
        this.waitTimer = 0;
        if (this.status === 'live') return;
        this.waitedLong = true;
        this._applyLayers();
      }, STREAM_SILENT_MS);
    }
    this._applyLayers();
    // A figure measured while the video played means nothing once it has stopped.
    if (status !== 'live' || this.held) this.onFrameRate(null);
    this.onStatus(status);
  }
}
