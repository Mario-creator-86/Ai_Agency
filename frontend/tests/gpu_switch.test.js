import test from 'node:test';
import assert from 'node:assert/strict';
import { gpuWords, mountGpuSwitch, offAnswer, offCommand } from '../src/gpu_switch.js';

const off = {
  configured: true, mock: false, rate_usd_per_hour: '4.00',
  endpoints: [{ purpose: 'image', endpoint_id: 'ep-s', state: 'OFF', workers_max: 0, running: 0 }],
  sessions: [], last_off: { at: '2026-10-08T20:00:00+00:00', reason: 'STEP_DONE', verified: true },
  words_ro: 'GPU oprit.',
};

test('the switch says off, on with the step, or unknown', () => {
  assert.deepEqual(gpuWords(off).label, 'GPU oprit');
  assert.equal(gpuWords(off).tone, 'off');
  assert.match(gpuWords(off).detail, /4\.00 USD\/oră/);
  const on = { ...off, endpoints: [{ ...off.endpoints[0], state: 'ON', workers_max: 1 }],
    sessions: [{ id: 's', purpose: 'image', step: 'stills', storyboard_id: 'f' }] };
  assert.equal(gpuWords(on).label, 'GPU pornit — pas: stills');
  assert.equal(gpuWords(on).tone, 'on');
  const unknown = { ...off, endpoints: [{ ...off.endpoints[0], state: 'UNKNOWN' }] };
  assert.equal(gpuWords(unknown).label, 'GPU: stare necunoscută');
  assert.equal(gpuWords(unknown).tone, 'unknown');
  assert.equal(gpuWords(null).tone, 'unknown');
});

test('a job RunPod has not started yet says the unbilled model wait', () => {
  const waiting = { ...off, endpoints: [{ ...off.endpoints[0], state: 'ON', workers_max: 1,
    model_wait_ro: 'aștept descărcarea modelului (neplătită)' }],
    sessions: [{ id: 's', purpose: 'image', step: 'stills', storyboard_id: 'f' }],
    model_wait_ro: 'aștept descărcarea modelului (neplătită)' };
  assert.equal(gpuWords(waiting).label, 'GPU: aștept descărcarea modelului (neplătită) — pas: stills');
  assert.equal(gpuWords(waiting).tone, 'on');
  assert.equal(gpuWords({ ...waiting, model_wait_ro: null }).label, 'GPU pornit — pas: stills');
});

test('the off command and its answer', () => {
  assert.deepEqual(offCommand('c-1'), { schema_version: 1, command_id: 'c-1' });
  assert.equal(offAnswer({ verified: true, words_ro: 'GPU-ul RunPod este oprit și verificat.' }),
    'GPU-ul RunPod este oprit și verificat.');
  assert.match(offAnswer({ verified: false, readings: [{}] }), /nu a confirmat/);
});

/** A few DOM pieces, enough for the switch: elements with text, attributes and listeners. */
function fakeDocument() {
  const make = tag => ({
    tagName: tag, children: [], hidden: false, disabled: false, textContent: '', title: '',
    className: '', dataset: {}, listeners: {}, type: '',
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    setAttribute(name, value) { this[name] = value; },
    addEventListener(name, fn) { this.listeners[name] = fn; },
  });
  const container = make('div');
  container.ownerDocument = { createElement: make };
  container.hidden = true;
  return container;
}

test('hidden without RunPod; the button switches off once however often it is pressed', async () => {
  const calls = [];
  let status = { ...off, configured: false };
  let release;
  const api = async (path, options = {}) => {
    calls.push([path, options.method || 'GET', options.body ? JSON.parse(options.body) : null]);
    if (path.startsWith('/runpod/gpu/off')) {
      await new Promise(resolve => { release = resolve; });
      return { command_id: 'x', verified: true, readings: [], words_ro: 'GPU-ul RunPod este oprit și verificat.' };
    }
    return status;
  };
  const said = [];
  const container = fakeDocument();
  const control = mountGpuSwitch(container, { api, notify: m => said.push(m), intervalMs: 0, uuid: () => 'u-1' });
  await control.refresh();
  assert.equal(container.hidden, true);
  status = { ...off, endpoints: [{ ...off.endpoints[0], state: 'ON' }],
    sessions: [{ id: 's', purpose: 'image', step: 'motion' }] };
  await control.refresh();
  assert.equal(container.hidden, false);
  const [label, button] = container.children;
  assert.equal(label.textContent, 'GPU pornit — pas: motion');
  assert.equal(button.textContent, 'Oprește GPU acum');
  assert.equal(button.disabled, false);
  const first = button.listeners.click();
  const second = button.listeners.click();
  assert.equal(button.disabled, true);
  await new Promise(resolve => setTimeout(resolve, 0));
  release();
  await first; await second;
  const offs = calls.filter(c => c[0] === '/runpod/gpu/off');
  assert.equal(offs.length, 1);
  assert.deepEqual(offs[0][2], { schema_version: 1, command_id: 'u-1' });
  assert.deepEqual(said, ['GPU-ul RunPod este oprit și verificat.']);
  control.stop();
});
