import { Config, Flags, PixelStreaming } from '@epicgames-ps/lib-pixelstreamingfrontend-ue5.8';
import { streamLayers } from './hq_stream_config.js';

/** How often a frame of the live video is kept, to be shown frozen if the stream drops. */
const STILL_COPY_MS = 2000;

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
   * @param {{signallingUrl: string, streamerId: string, retryMs: number}} settings
   * @param {{onStatus?: (status: 'connecting'|'live'|'offline') => void}} [options]
   */
  constructor(viewport, settings, options = {}) {
    this.viewport = viewport;
    this.settings = settings;
    this.onStatus = options.onStatus || (() => {});
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
    this.badge.textContent = 'Reconnecting to the live headquarters…';
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
    this._setStatus('offline');
    window.clearTimeout(this.retryTimer);
    this.retryTimer = window.setTimeout(() => this.stream.reconnect(), this.settings.retryMs);
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
    this.status = status;
    window.clearInterval(this.stillTimer);
    if (status === 'live') {
      this.stillTimer = window.setInterval(() => this._copyFrame(), STILL_COPY_MS);
    }
    const layers = streamLayers(status, this.hasStill);
    this.layer.hidden = !layers.layer;
    // the library's video is hidden by a class, not touched: its frozen copy shows instead
    this.layer.classList.toggle('still', layers.still);
    this.still.hidden = !layers.still;
    this.badge.hidden = !layers.reconnecting;
    this.onStatus(status);
  }
}
