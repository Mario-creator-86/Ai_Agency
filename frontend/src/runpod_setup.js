// The Owner's «RunPod pornit» switch and the read-only «Pașii configurării» checklist, on the
// RunPod connection's card in Setări → Video și sunet (his card, 2026-10-09: the switch replaces
// editing RUNPOD_ENABLED in .env).
//
// GET  /api/v1/runpod/integrations/{id}/setup        the last check (nothing is called)
// POST /api/v1/runpod/integrations/{id}/setup/check  «Verifică pașii»: GET / HEAD reads only
// PUT  /api/v1/runpod/integrations/{id}/switch       {schema_version: 1, on}
//
// Turning ON asks a second press (it lets approved paid steps start the GPU); turning OFF is one
// press and immediate (it spends nothing and switches the GPU off). The server never sends a
// secret; the page shows only «salvată» / «lipsește» and links to the console pages.

/** @typedef {{key: string, title_ro?: string, status: string, words_ro: string, link?: string|null, link_ro?: string|null}} SetupRow */
/** @typedef {{on: boolean, source?: string, can_turn_on?: boolean, why_not_ro?: string|null, words_ro?: string}} SwitchState */
/** @typedef {{integration_id?: string, checked_at?: string|null, switch: SwitchState, rows: SetupRow[]}} SetupAnswer */

export const STATUS_LABEL = /** @type {Record<string, string>} */ ({
  green: 'verde',
  red: 'roșu',
  grey: 'nu se poate verifica încă',
});

/** The only places a row may link to (the console pages of his accounts). */
const LINK_PREFIXES = [
  'https://console.runpod.io/',
  'https://huggingface.co/',
  'https://dash.cloudflare.com/',
  'https://github.com/',
];

/** @param {unknown} url @returns {string|null} */
export function safeLink(url) {
  if (typeof url !== 'string') return null;
  return LINK_PREFIXES.some(prefix => url.startsWith(prefix)) ? url : null;
}

/** @param {boolean} on */
export function switchCommand(on) {
  return { schema_version: 1, on: Boolean(on) };
}

/** @param {SetupRow} row @returns {{tone: string, label: string, words: string}} */
export function rowView(row) {
  const tone = row.status in STATUS_LABEL ? row.status : 'grey';
  return { tone, label: STATUS_LABEL[tone], words: String(row.words_ro || '') };
}

/**
 * Draws the switch and the checklist into a RunPod connection's card and loads the last check.
 * @param {any} card the connection's <article>
 * @param {{id: string}} item the connection
 * @param {{api: (path: string, options?: any) => Promise<any>}} deps
 */
export async function renderRunPodSetup(card, item, { api }) {
  const doc = card.ownerDocument || document;
  /** @param {string} tag @param {string} [text] @param {string} [className] */
  const make = (tag, text = '', className = '') => {
    const element = doc.createElement(tag);
    element.textContent = text;
    element.className = className;
    return element;
  };
  const base = `/runpod/integrations/${encodeURIComponent(item.id)}`;
  const box = make('section', '', 'runpod-setup');
  card.append(box);
  /** @type {SetupAnswer|null} */
  let state = null;
  let note = '';
  let noteError = false;
  let armed = false;
  let busy = false;

  function draw() {
    box.replaceChildren();
    const toggle = make('div', '', 'runpod-switch');
    const on = Boolean(state?.switch?.on);
    toggle.dataset.on = on ? 'yes' : 'no';
    toggle.append(make('h4', 'RunPod pornit'));
    toggle.append(make('p', state?.switch?.words_ro || (state ? '' : 'Se încarcă starea RunPod…'), 'helper'));
    if (state && !on && state.switch?.can_turn_on === false && state.switch?.why_not_ro) {
      toggle.append(make('p', state.switch.why_not_ro, 'settings-limitation'));
    }
    const press = make('button', on ? 'Oprește RunPod' : armed ? 'Confirmă pornirea RunPod' : 'Pornește RunPod', on ? 'secondary' : 'primary');
    press.disabled = busy || !state || (!on && state.switch?.can_turn_on === false);
    press.addEventListener('click', () => (on ? turn(false) : armed ? turn(true) : arm()));
    toggle.append(press);
    if (note) {
      const said = make('p', note, noteError ? 'settings-error' : 'helper');
      said.setAttribute('role', 'status');
      toggle.append(said);
    }
    box.append(toggle);

    box.append(make('h4', 'Pașii configurării'));
    if (state?.checked_at) box.append(make('p', `Ultima verificare: ${new Date(state.checked_at).toLocaleString('ro-RO')}`, 'helper'));
    const list = make('ul', '', 'runpod-steps');
    for (const row of state?.rows || []) {
      const view = rowView(row);
      const line = make('li', '', `runpod-step runpod-step-${view.tone}`);
      line.dataset.status = view.tone;
      line.append(make('span', view.label, 'runpod-step-status'), make('strong', row.title_ro || row.key), make('span', view.words, 'runpod-step-words'));
      const href = safeLink(row.link);
      if (href) {
        const link = make('a', row.link_ro || 'Deschide pagina');
        link.href = href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        line.append(link);
      }
      list.append(line);
    }
    box.append(list);
    const check = make('button', 'Verifică pașii', 'secondary');
    check.disabled = busy;
    check.title = 'Citește endpointurile RunPod și bucketul (doar citire, nu pornește nimic și nu costă).';
    check.addEventListener('click', () => load(true));
    box.append(check);
  }

  function arm() {
    armed = true;
    note = 'Apasă încă o dată ca să pornești RunPod. Fiecare pas plătit tot îți cere aprobarea.';
    noteError = false;
    draw();
  }

  /** @param {boolean} on */
  async function turn(on) {
    if (busy) return;
    busy = true;
    armed = false;
    draw();
    try {
      const answer = await api(`${base}/switch`, { method: 'PUT', body: JSON.stringify(switchCommand(on)) });
      // The switch box already shows the answer's sentence: no second copy as a note.
      note = '';
      noteError = false;
      if (state) {
        const now = Boolean(answer?.on);
        // The checklist's own «Comutatorul» row says what the box says (no stale row).
        const rows = (state.rows || []).map(row => row.key === 'switch'
          ? { ...row, status: now ? 'green' : 'red', words_ro: answer?.words_ro || row.words_ro }
          : row);
        state = { ...state, switch: { ...state.switch, ...answer }, rows };
      }
    } catch (error) {
      note = error instanceof Error ? error.message : String(error);
      noteError = true;
    } finally {
      busy = false;
      draw();
    }
  }

  /** @param {boolean} fresh */
  async function load(fresh) {
    if (busy) return;
    busy = true;
    if (fresh) { note = 'Se verifică pașii (doar citire)…'; noteError = false; }
    draw();
    try {
      state = fresh
        ? await api(`${base}/setup/check`, { method: 'POST' })
        : await api(`${base}/setup`);
      if (fresh) note = 'Verificarea pașilor s-a încheiat.';
    } catch (error) {
      note = error instanceof Error ? error.message : String(error);
      noteError = true;
    } finally {
      busy = false;
      draw();
    }
  }

  draw();
  await load(false);
}
