import { Config, Flags, PixelStreaming } from '@epicgames-ps/lib-pixelstreamingfrontend-ue5.8';

/**
 * Shows the Unreal headquarters, streamed live over Pixel Streaming, on top of the page's own
 * renderer. The video lets clicks through to the renderer underneath, which still knows where
 * every employee sits; when the stream drops, the video hides and the renderer is seen again, and
 * the stream is retried.
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
    this.layer = document.createElement('div');
    // "fixed-size": the page's stylesheet sizes the layer; the library would otherwise write an
    // inline style, which the page's Content-Security-Policy refuses.
    this.layer.className = 'live-stream-layer fixed-size';
    this.layer.hidden = true;
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

  _setStatus(status) {
    this.status = status;
    this.layer.hidden = status !== 'live';
    this.onStatus(status);
  }
}
