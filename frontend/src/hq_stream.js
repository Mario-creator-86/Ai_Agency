import { Config, Flags, PixelStreaming } from '@epicgames-ps/lib-pixelstreamingfrontend-ue5.8';
import { streamLayers } from './hq_stream_config.js';

/** How often a frame of the live video is kept, to be shown frozen if the stream drops. */
const STILL_COPY_MS = 2000;
/**
 * How long the page waits for a picture before it asks the signalling server again. Measured
 * 2026-09-19: after a restart Unreal joined signalling 22 s after the server started, the library
 * asked for streamers for about 11 s and then stopped, and the page showed no picture for ten
 * minutes. A negotiation under way takes a few seconds, so half a minute leaves it alone.
 */
const CONNECTING_RETRY_MS = 30000;
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
   * @param {{onStatus?: (status: 'connecting'|'live'|'offline') => void, onFrameRate?: (fps: number|null) => void}} [options]
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
    this.stream.addEventListener('playStream', () => this._setStatus('live'));
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
    this.onFrameRate(inboundFrameRate(event?.data?.aggregatedStats));
  }

  start() {
    this._setStatus('connecting');
    this.stream.connect();
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

  /** Keeps the video's current frame in the still canvas (the video belongs to the library). */
  _copyFrame() {
    const video = this.layer.querySelector('video');
    if (!video || !video.videoWidth || video.readyState < 2) return;
    if (this.still.width !== video.videoWidth || this.still.height !== video.videoHeight) {
      this.still.width = video.videoWidth;
      this.still.height = video.videoHeight;
    }
    const context = this.still.getContext('2d');
    if (!context) return;
    context.drawImage(video, 0, 0);
    this.hasStill = true;
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
    window.clearInterval(this.stillTimer);
    if (status === 'live') {
      this._copyFrame();
      this.stillTimer = window.setInterval(() => this._copyFrame(), STILL_COPY_MS);
    }
    const layers = streamLayers(status, this.hasStill);
    // the layer always covers the page's own renderer while a stream is configured
    this.layer.hidden = false;
    // the library's video is hidden by a class, not touched: the frozen copy or the note shows
    this.layer.classList.toggle('paused', status !== 'live');
    this.layer.classList.toggle('waiting', layers.waiting);
    this.still.hidden = !layers.still;
    this.badge.hidden = !layers.note;
    this.badge.textContent = NOTES[layers.note] || '';
    // A figure measured while the video played means nothing once it has stopped.
    if (status !== 'live') this.onFrameRate(null);
    this.onStatus(status);
  }
}
