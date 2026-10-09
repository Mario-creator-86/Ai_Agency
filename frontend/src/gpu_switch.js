// The Owner's RunPod GPU switch (2026-10-08): what the GPU is doing, and «Oprește GPU acum».
// The state comes from GET /api/v1/runpod/gpu (the guard's last reading); the button sends
// POST /api/v1/runpod/gpu/off. Off is always safe (it spends nothing, under STOP AUTONOMIE
// too), so there is no confirmation; a double press sends one command. Hidden when the studio
// has no RunPod connection.

/**
 * @typedef {{purpose: string, endpoint_id: string, state: string, workers_max?: number|null,
 *   running?: number|null, model_wait_ro?: string|null}} GpuEndpoint
 * @typedef {{id: string, purpose: string, step: string, storyboard_id?: string|null}} GpuSession
 * @typedef {{configured: boolean, mock?: boolean, rate_usd_per_hour?: string,
 *   endpoints?: GpuEndpoint[], sessions?: GpuSession[],
 *   last_off?: {at: string, reason: string, verified: boolean|null}|null, words_ro?: string,
 *   model_wait_ro?: string|null}} GpuStatus
 */

const OFF_REASONS = /** @type {Record<string, string>} */ ({
  STEP_DONE: 'după ultimul rezultat',
  STEP_FAILED: 'după un pas oprit',
  OWNER_OFF: 'de tine',
  GUARD_ORPHAN: 'de paznic, la pornire',
  GUARD_STALE: 'de paznic',
  GUARD_TTL: 'de paznic, după limita de timp',
  SHUTDOWN: 'la oprirea studioului',
  LAUNCHER_STOP: 'la închiderea studioului',
});

/**
 * The switch's words: label, tone ('off'|'on'|'unknown') and the longer detail.
 * @param {GpuStatus|null|undefined} status
 * @returns {{label: string, tone: 'off'|'on'|'unknown', detail: string}}
 */
export function gpuWords(status) {
  if (!status || !status.configured) return { label: '', tone: 'unknown', detail: '' };
  const parts = [];
  if (status.words_ro) parts.push(status.words_ro);
  if (status.rate_usd_per_hour) parts.push(`Buget ${status.rate_usd_per_hour} USD/oră, cel mult 1 GPU.`);
  const last = status.last_off;
  if (last && last.at) {
    const how = OFF_REASONS[last.reason] || last.reason;
    parts.push(`Ultima oprire ${how}: ${last.verified ? 'verificată' : 'neverificată'}.`);
  }
  const detail = parts.join(' ');
  if (status.mock) return { label: 'GPU: simulare', tone: 'off', detail };
  const sessions = status.sessions || [];
  const endpoints = status.endpoints || [];
  if (sessions.length) {
    const steps = [...new Set(sessions.map(s => s.step))].join(', ');
    // RunPod has not started the worker yet (a cache miss downloads the model): unbilled.
    if (status.model_wait_ro) return { label: `GPU: ${status.model_wait_ro} — pas: ${steps}`, tone: 'on', detail };
    return { label: `GPU pornit — pas: ${steps}`, tone: 'on', detail };
  }
  if (endpoints.some(e => e.state === 'ON')) {
    return { label: 'GPU pornit — pas: niciunul', tone: 'on', detail };
  }
  if (endpoints.length && endpoints.every(e => e.state === 'OFF')) {
    return { label: 'GPU oprit', tone: 'off', detail };
  }
  return { label: 'GPU: stare necunoscută', tone: 'unknown', detail };
}

/**
 * @param {string} commandId
 * @returns {{schema_version: 1, command_id: string}}
 */
export function offCommand(commandId) {
  return { schema_version: 1, command_id: commandId };
}

/**
 * What the Owner reads after his press.
 * @param {{verified?: boolean, words_ro?: string, readings?: unknown[]}|null|undefined} result
 * @returns {string}
 */
export function offAnswer(result) {
  if (result && result.words_ro) return result.words_ro;
  if (result && result.verified) return 'GPU-ul RunPod este oprit și verificat.';
  return 'Am trimis oprirea GPU-ului RunPod, dar nu a confirmat încă; paznicul verifică din nou la fiecare minut.';
}

/**
 * Mount the switch in ``container`` (a <div id="gpu-switch" hidden>).
 * @param {any} container
 * @param {{api: (path: string, options?: any) => Promise<any>, notify: (message: string) => void,
 *   intervalMs?: number, uuid?: () => string}} options
 * @returns {{refresh(): Promise<void>, stop(): void}}
 */
export function mountGpuSwitch(container, { api, notify, intervalMs = 15000, uuid }) {
  const doc = container.ownerDocument || document;
  const label = doc.createElement('span');
  label.className = 'switch-state gpu-switch-state';
  const button = doc.createElement('button');
  button.type = 'button';
  button.className = 'cam-btn cam-worded gpu-switch-off';
  button.textContent = 'Oprește GPU acum';
  container.append(label, button);
  const newId = uuid || (() => crypto.randomUUID());
  let pressing = /** @type {Promise<void>|null} */ (null);
  let stopped = false;

  async function refresh() {
    try {
      const status = /** @type {GpuStatus} */ (await api('/runpod/gpu'));
      container.hidden = !status || !status.configured;
      const words = gpuWords(status);
      label.textContent = words.label;
      label.title = words.detail;
      container.title = words.detail;
      container.dataset.tone = words.tone;
    } catch {
      if (!container.hidden) {
        label.textContent = 'GPU: stare necunoscută';
        container.dataset.tone = 'unknown';
      }
    }
    button.disabled = Boolean(pressing);
  }

  async function press() {
    if (pressing) return pressing;
    button.disabled = true;
    pressing = (async () => {
      try {
        const result = await api('/runpod/gpu/off', {
          method: 'POST',
          body: JSON.stringify(offCommand(newId())),
          timeoutMs: 180000,
        });
        notify(offAnswer(result));
      } catch (failure) {
        notify(failure instanceof Error ? failure.message : String(failure));
      } finally {
        pressing = null;
        if (!stopped) await refresh();
      }
    })();
    return pressing;
  }

  button.addEventListener('click', () => press());
  const timer = intervalMs > 0 ? setInterval(() => { void refresh(); }, intervalMs) : null;
  if (timer) void refresh();
  return {
    refresh,
    stop() {
      stopped = true;
      if (timer) clearInterval(timer);
    },
  };
}
