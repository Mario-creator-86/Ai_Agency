import { renderYouTubeConnections } from './youtube_connections.js';

import './settings.css';

const sections = [['llm', 'Furnizori AI'], ['agents', 'Agenți'], ['media', 'Video și sunet'], ['social', 'Conturi și e-mail']];
const purposes = { image: 'Imagini', video: 'Video', voice: 'Voce / TTS', music: 'Muzică / sunet', youtube: 'YouTube', tiktok: 'TikTok', instagram: 'Instagram', facebook: 'Facebook', email: 'E-mail' };
const statuses = { SAVED: 'Salvat · neverificat', VERIFIED: 'Conexiune verificată', ACCESS_VERIFIED: 'Acces verificat · pipeline în așteptare', FAILED: 'Verificare eșuată' };

/** @param {string} tag @param {string} [text] @param {string} [className] @returns {HTMLElement} */
function node(tag, text = '', className = '') {
  const result = document.createElement(tag);
  result.textContent = text;
  result.className = className;
  return result;
}

/** @param {HTMLSelectElement} select @param {string} value @param {string} text */
function option(select, value, text) {
  const item = new Option(text, value);
  select.add(item);
}

/**
 * @param {(path: string, options?: any) => Promise<any>} api
 * @param {{ onChange?: () => Promise<void> | void }} [hooks]
 *   `onChange` runs after every successful change here. Assigning a model, verifying a
 *   provider or binding a channel all alter what the rest of the app should be showing —
 *   the office inspector in particular — and without this the app kept displaying the state
 *   from before the change until the page was reloaded.
 */
export function initSettings(api, hooks = {}) {
  const heading = document.querySelector('#workspace .page-heading');
  const open = node('button', 'Settings', 'secondary');
  open.id = 'open-settings';
  heading.append(open);
  const dialog = /** @type {HTMLDialogElement} */ (node('dialog', '', 'studio-dialog settings-dialog'));
  dialog.id = 'settings-dialog';
  dialog.setAttribute('aria-labelledby', 'settings-title');
  document.body.append(dialog);
  let data = null;
  let active = 'llm';
  let generation = 0;
  let pending = false;
  

  function reset() {
    generation++;
    data = null;
    pending = false;

    dialog.close();
    dialog.replaceChildren();
  }

  dialog.addEventListener('close', () => {
    void hooks.onChange?.();
  });

  function message(text, error = false) {
    const output = dialog.querySelector('.settings-message');
    if (!output) return;
    output.textContent = text;
    output.classList.toggle('settings-error', error);
  }

  async function refresh() {
    const current = generation;
    const result = await api('/settings');
    if (current !== generation || !dialog.open) return;
    data = result;
    render();
  }

  async function run(operation, success) {
    if (pending) return;
    pending = true;
    const current = generation;
    dialog.querySelectorAll('button, input, select').forEach(el => { /** @type {HTMLButtonElement} */ (el).disabled = true; });
    try {
      const result = await operation();
      if (current !== generation) return;
      await refresh();
      try {
        await hooks.onChange?.();
      } catch {
        // Telling the rest of the app is best effort; the change itself already succeeded.
      }
      message(result?.message || success);
    } catch (error) {
      if (current === generation) message(error.message, true);
    } finally {
      if (current === generation) {
        pending = false;
        dialog.querySelectorAll('button, input, select').forEach(el => { /** @type {HTMLButtonElement} */ (el).disabled = false; });
      }
    }
  }

  function render() {
    dialog.replaceChildren();

    const header = node('div', '', 'dialog-header');
    const title = node('h2', 'Settings');
    title.id = 'settings-title';
    const close = node('button', 'Închide', 'quiet');
    close.addEventListener('click', reset);
    header.append(title, close);
    dialog.append(header, node('p', 'Conectează doar serviciile pe care vrei să le folosească studioul.', 'settings-intro'));
    const nav = node('nav', '', 'settings-tabs');
    nav.setAttribute('aria-label', 'Secțiuni Settings');
    for (const [key, label] of sections) {
      const button = node('button', label, key === active ? 'primary' : 'quiet');
      button.setAttribute('aria-current', key === active ? 'page' : 'false');
      button.addEventListener('click', () => { active = key; render(); });
      nav.append(button);
    }
    dialog.append(nav);
    const output = node('p', '', 'settings-message');
    output.setAttribute('role', 'status');
    dialog.append(output);
    const content = node('section', '', 'settings-content');
    dialog.append(content);
    if (!data) { content.append(node('p', 'Se încarcă setările…')); return; }
    if (active === 'agents') { renderAgents(content); return; }
    // YouTube channels are not a generic catalog entry: they carry an OAuth grant, a channel
    // identity read back from Google, and their own connect/reconnect/disconnect lifecycle.
    // They lead the tab, and the catalog picker below gets its own heading so the two do not
    // read as one list.
    if (active === 'social') {
      renderYouTubeConnections(content, { api, notify: message });
      content.append(node('h3', 'Alte conturi și e-mail'));
    }
    const row = node('div', '', 'settings-add');
    const picker = /** @type {HTMLSelectElement} */ (node('select'));
    picker.setAttribute('aria-label', 'Serviciu de adăugat');
    option(picker, '', 'Alege serviciul…');
    for (const [kind, spec] of Object.entries(data.catalog)) {
      if (spec.group === active) option(picker, kind, spec.label);
    }
    const add = node('button', 'Adaugă conexiune', 'secondary');
    add.addEventListener('click', () => {
      if (picker.value) edit(content, picker.value, null);
      else message('Alege mai întâi un serviciu.', true);
    });
    row.append(picker, add);
    content.append(row);
    if (active === 'llm') renderLegacyProviders(content);
    const items = data.integrations.filter(item => data.catalog[item.kind].group === active);
    if (!items.length) content.append(node('p', 'Nu ai adăugat încă nicio conexiune din catalog în această secțiune.', 'helper'));
    const list = node('div', '', 'settings-connections');
    for (const item of items) {
      const spec = data.catalog[item.kind];
      const card = node('article', '', 'settings-card');
      card.append(node('h3', item.name), node('p', `${spec.label} · ${statuses[item.status] || item.status}`, 'helper'));
      if (item.checked_at) card.append(node('p', `Verificat: ${new Date(item.checked_at).toLocaleString('ro-RO')}`, 'helper'));
      // Three different truths, and the card says which one applies. "stored" means the
      // credentials are kept but nothing in the pipeline calls this vendor yet; "media" means
      // it will be called, but only once it is verified and selected for a purpose.
      if (spec.runtime === 'stored') {
        card.append(node('p', 'Date salvate. Folosirea în pipeline nu este încă disponibilă.', 'settings-limitation'));
      } else if (spec.runtime === 'media' && item.status !== 'ACCESS_VERIFIED' && item.status !== 'VERIFIED') {
        card.append(node('p', 'Verifică accesul, apoi selectează serviciul mai jos pentru scopul dorit. Până atunci randările folosesc substitute, iar QC le blochează de la publicare.', 'settings-limitation'));
      }
      const actions = node('div', '', 'settings-actions');
      const modify = node('button', 'Editează', 'quiet');
      modify.addEventListener('click', () => edit(content, item.kind, item));
      actions.append(modify);
      if (item.kind !== 'runway') {
        const check = node('button', spec.runtime === 'llm' ? 'Verifică și încarcă modelele' : 'Verifică accesul', 'secondary');
        check.addEventListener('click', () => run(() => api(`/settings/integrations/${item.id}/check`, { method: 'POST' }), 'Verificare terminată.'));
        actions.append(check);
      }
      const remove = node('button', 'Șterge conexiunea', 'quiet');
      remove.addEventListener('click', () => {
        if (remove.dataset.armed !== 'yes') {
          remove.dataset.armed = 'yes';
          remove.textContent = 'Confirmă ștergerea';
          return;
        }
        run(() => api(`/settings/integrations/${item.id}?expected_version=${item.version}`, { method: 'DELETE' }), 'Conexiune ștearsă.');
      });
      actions.append(remove);
      card.append(actions);
      list.append(card);
    }
    content.append(list);
    if (active === 'media' || active === 'social') renderSelections(content, items);
    if (active === 'social' && data.legacy_youtube_configured) content.append(node('p', 'Există și o configurație YouTube în mediul serverului. O selecție YouTube salvată aici are prioritate.', 'helper'));
  }

  function edit(container, kind, existing) {
    container.querySelector('.settings-editor')?.remove();

    const spec = data.catalog[kind];
    const form = /** @type {HTMLFormElement} */ (node('form', '', 'settings-editor'));
    form.append(node('h3', `${existing ? 'Editează' : 'Adaugă'} · ${spec.label}`));
    const hint = node('p', spec.help, 'helper');
    const docs = /** @type {HTMLAnchorElement} */ (node('a', 'Deschide documentația serviciului'));
    docs.href = spec.docs;
    docs.target = '_blank';
    docs.rel = 'noopener noreferrer';
    form.append(hint, docs);
    const grid = node('div', '', 'settings-fields');
    const fields = [{ key: 'name', label: 'Numele conexiunii', kind: 'text', required: true, secret: false, choices: [] }, ...spec.fields];
    for (const field of fields) {
      const label = node('label', field.label);
      let input;
      if (field.choices.length) {
        input = /** @type {HTMLSelectElement} */ (node('select'));
        option(input, '', 'Alege…');
        for (const choice of field.choices) option(input, choice, choice);
      } else {
        input = /** @type {HTMLInputElement} */ (node('input'));
        input.type = field.secret ? 'password' : field.kind;
        input.autocomplete = 'off';
        input.spellcheck = false;
        if (field.kind === 'number') { input.min = '1'; input.max = '65535'; }
        input.maxLength = field.secret ? 8192 : field.key === 'name' ? 100 : 500;
      }
      input.name = field.key;
      input.required = field.required && !(field.secret && existing?.secret_fields.includes(field.key));
      input.value = field.secret ? '' : field.key === 'name' ? existing?.name || '' : existing?.config[field.key] || '';
      label.append(input);
      if (field.secret && existing?.secret_fields.includes(field.key)) label.append(node('small', 'Salvată. Lasă gol pentru a păstra cheia.', 'helper'));
      grid.append(label);
    }
    form.append(grid, node('p', 'Cheile sunt criptate pe server. Nu sunt afișate din nou după salvare.', 'helper'));
    const save = /** @type {HTMLButtonElement} */ (node('button', 'Salvează conexiunea', 'primary'));
    save.type = 'submit';
    const cancel = /** @type {HTMLButtonElement} */ (node('button', 'Renunță', 'quiet'));
    cancel.type = 'button';
    cancel.addEventListener('click', () => { form.reset(); form.remove(); });
    form.append(save, cancel);
    form.addEventListener('submit', event => {
      event.preventDefault();
      const values = new FormData(form);
      const config = {}, secrets = {};
      for (const field of spec.fields) {
        const value = String(values.get(field.key) || '').trim();
        if (value) (field.secret ? secrets : config)[field.key] = value;
      }
      const payload = { kind, name: String(values.get('name')).trim(), config, secrets, expected_version: existing?.version || 0 };
      const identifier = existing?.id || crypto.randomUUID();
      run(async () => {
        try { return await api(`/settings/integrations/${identifier}`, { method: 'PUT', body: JSON.stringify(payload) }); }
        finally { form.querySelectorAll('input[type=password]').forEach(input => { /** @type {HTMLInputElement} */ (input).value = ''; }); }
      }, 'Conexiune salvată. Verifică accesul înainte de utilizare.');
    });
    container.prepend(form);
    form.querySelector('input')?.focus();
  }

  function renderSelections(container, items) {
    const available = Object.entries(purposes).filter(([purpose]) => items.some(item => [...data.catalog[item.kind].purposes, item.kind].includes(purpose)));
    if (!available.length) return;
    container.append(node('h3', active === 'media' ? 'Serviciile alese pentru producție' : 'Conturile alese'));
    for (const [purpose, label] of available) {
      const row = node('div', '', 'settings-routing');
      const select = /** @type {HTMLSelectElement} */ (node('select'));
      select.setAttribute('aria-label', label);
      option(select, '', 'Fără selecție');
      for (const item of items) if ([...data.catalog[item.kind].purposes, item.kind].includes(purpose)) option(select, item.id, item.name);
      select.value = data.selections[purpose]?.integration_id || '';
      const save = node('button', 'Aplică', 'secondary');
      save.addEventListener('click', () => {
        run(() => api(`/settings/selections/${purpose}`, { method: 'PUT', body: JSON.stringify({ integration_id: select.value || null, expected_version: data.selections[purpose]?.version || 0 }) }), 'Selecție salvată.');
      });
      row.append(node('span', label), select, save);
      container.append(row);
    }
  }

  /**
   * Providers that predate the Settings screen — the local Ollama endpoint written by the
   * seed. Their record says only what the seed knew, which is nothing about whether the
   * endpoint answers; this card is the control that turns that into a measured state.
   */
  function renderLegacyProviders(container) {
    for (const provider of data.legacy_providers || []) {
      const card = node('article', '', 'settings-card');
      const verified = Boolean(provider.last_health_check);
      card.append(
        node('h3', provider.name),
        node('p', `${provider.provider_type} · ${provider.base_url}`, 'helper'),
      );
      card.append(
        node(
          'p',
          verified
            ? `Verificat: ${new Date(provider.last_health_check).toLocaleString('ro-RO')}`
            : 'Adăugat automat la instalare. Nu a fost contactat niciodată, deci modelele lui nu pot fi alocate încă.',
          verified ? 'helper' : 'settings-limitation',
        ),
      );
      const actions = node('div', '', 'settings-actions');
      const check = node('button', 'Verifică și încarcă modelele', 'secondary');
      check.addEventListener('click', () => {
        run(async () => {
          const result = await api(`/providers/${provider.id}/sync-models`, { method: 'POST' });
          const available = (result.models || []).filter(model => model.is_available).length;
          return {
            message: available
              ? `${provider.name} a răspuns: ${available} modele disponibile.`
              : `${provider.name} a răspuns, dar nu oferă niciun model.`,
          };
        }, '');
      });
      actions.append(check);
      card.append(actions);
      container.append(card);
    }
  }

  function renderAgents(container) {
    container.append(node('p', 'Adaugă și verifică un furnizor AI, apoi alocă un model fiecărui agent. Testul rulează o singură cerere reală prin modelul alocat.', 'helper'));
    if (!data.agents.length) container.append(node('p', 'Nu există încă agenți în studio.'));
    for (const agent of data.agents) {
      const card = node('article', '', 'settings-card');
      const role = data.roles.find(role => role.id === agent.role_id);
      card.append(node('h3', agent.display_name), node('p', role?.name || 'Rol neidentificat', 'helper'));
      const current = data.models.find(model => model.id === agent.model_id);
      card.append(node('p', `Model actual: ${current?.model_name || 'Necunoscut'}`, 'helper'));
      const select = /** @type {HTMLSelectElement} */ (node('select'));
      select.setAttribute('aria-label', `Model pentru ${agent.display_name}`);
      option(select, '', 'Alege un model disponibil…');
      for (const model of data.models) {
        if (!model.is_available || !(role?.required_capabilities || []).every(cap => model.capabilities.includes(cap))) continue;
        const connection = data.integrations.find(item => item.id === model.provider_id);
        option(select, model.id, `${connection?.name || 'Furnizor existent'} · ${model.model_name}`);
      }
      select.value = agent.model_id;
      const save = node('button', 'Alocă modelul', 'secondary');
      save.addEventListener('click', () => {
        if (!select.value) { message('Alege un model disponibil și compatibil cu rolul.', true); return; }
        run(() => api(`/settings/agents/${agent.id}/model`, { method: 'PUT', body: JSON.stringify({ model_id: select.value, expected_version: agent.version }) }), 'Model alocat agentului.');
      });
      const test = node('button', 'Testează răspunsul', 'secondary');
      test.addEventListener('click', () => {
        run(async () => {
          const result = await api(`/settings/agents/${agent.id}/test`, { method: 'POST' });
          const text = String(result.output_text || '').replace(/\s+/g, ' ').trim();
          if (result.status === 'SUCCEEDED') {
            return text
              ? { message: `${result.model_name} a răspuns: „${text.slice(0, 140)}”` }
              : { message: 'Modelul a rulat (token-uri contorizate), dar nu a produs text vizibil — mărește bugetul sau încearcă alt model.' };
          }
          throw new Error(`Testul nu a rulat: ${result.status}${result.error_detail ? ` — ${result.error_detail}` : ''}`);
        }, '');
      });
      const controls = node('div', '', 'settings-actions');
      controls.append(select, save, test);
      card.append(controls);
      container.append(card);
    }
  }

  open.addEventListener('click', async () => {
    generation++;
    dialog.showModal();
    render();
    try { await refresh(); } catch (error) { message(error.message, true); }
  });
  dialog.addEventListener('cancel', event => { event.preventDefault(); reset(); });
  return { reset };
}
