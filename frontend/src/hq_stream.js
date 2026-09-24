import { Config, Flags, PixelStreaming } from '@epicgames-ps/lib-pixelstreamingfrontend-ue5.8';
import { HELD_STILL_MS, streamLayers } from './hq_stream_config.js';

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
const NOTES = {
  reconnecting: 'Se reconectează la sediul live…',
  starting: 'Pornește sediul live…',
};

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
   * @param {{signallingUrl: string, streamerId: string, retryMs: number, connectingRetryMs?: number}} settings
   * @param {{onStatus?: (status: 'connecting'|'live'|'offline') => void, onFrameRate?: (fps: number|null) => void, held?: () => boolean}} [options]
   */
  constructor(viewport, settings, options = {}) {
    this.viewport = viewport;
    this.settings = settings;
    this.onStatus = options.onStatus || (() => {});
    this.onFrameRate = options.onFrameRate || (() => {});
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
    this.badge = document.createElement('div');
    this.badge.className = 'live-stream-badge';
    this.badge.textContent = NOTES.reconnecting;
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
    /** The page's camera, laid on the video (setView). @type {{k: number, tx: number, ty: number}|null} */
    this.view = null;
    this.stream.addEventListener('playStream', () => {
      this._setStatus('live');
      // the library may have made a new video element for this connection
      this._applyView();
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
    this._setStatus('connecting');
    this.stream.connect();
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
    if (this._copyFrame()) this.keptLive = true;
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
    return true;
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
        this.stream.reconnect();
        this._setStatus('connecting');
      }, wait);
    }
    window.clearTimeout(this.stillTimer);
    this.stillTimer = 0;
    if (status === 'live') {
      this.keptLive = false;
      this._keepFrames();
    }
    const layers = streamLayers(status, this.hasStill, this.held);
    // the layer always covers the page's own renderer while a stream is configured
    this.layer.hidden = false;
    // the library's video is hidden by a class, not touched: the frozen copy or the note shows
    this.layer.classList.toggle('paused', status !== 'live');
    this.layer.classList.toggle('held', layers.held);
    this.layer.classList.toggle('waiting', layers.waiting);
    this.still.hidden = !layers.still;
    this.badge.hidden = !layers.note;
    this.badge.textContent = NOTES[layers.note] || '';
    // A figure measured while the video played means nothing once it has stopped.
    if (status !== 'live' || this.held) this.onFrameRate(null);
    this.onStatus(status);
  }
}
