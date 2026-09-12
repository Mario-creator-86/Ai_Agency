import { renderYouTubeConnections } from './youtube_connections.js';
import { renderProviderProduction } from './provider_production.js';

import './settings.css';

const sections = [['llm', 'AI providers'], ['agents', 'Agents'], ['media', 'Video and sound'], ['social', 'Accounts and e-mail']];
// No 'youtube' purpose: a YouTube channel is chosen by connecting it, not by picking a saved
// credential row out of a list. The backend refuses that purpose for the same reason.
const purposes = { image: 'Images', video: 'Video', voice: 'Voice / TTS', music: 'Music / sound', tiktok: 'TikTok', instagram: 'Instagram', facebook: 'Facebook', email: 'E-mail' };
const statuses = { SAVED: 'Saved · not verified', VERIFIED: 'Connection verified', ACCESS_VERIFIED: 'Access verified · pipeline pending', FAILED: 'Verification failed' };

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
  // The page heading is gone; the Settings button lives in the top bar with the session.
  const heading = document.querySelector('.topbar-right') || document.querySelector('#workspace');
  const open = node('button', 'Settings', 'secondary');
  open.id = 'open-settings';
  open.classList.add('topbar-logout');
  heading.prepend(open);
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

  /** What the last auto-configure chose, kept so the reload it triggers can show it. */
  let autoConfigReport = [];

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
      message(result?.message || success, result?.status === 'FAILED' || result?.discovery_status === 'ERROR');
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
    const close = node('button', '✕', 'dialog-close');
    close.setAttribute('aria-label', 'Close');
    close.title = 'Close';
    close.addEventListener('click', reset);
    header.append(title, close);
    dialog.append(header, node('p', 'Connect only the services you want the studio to use.', 'settings-intro'));
    const nav = node('nav', '', 'settings-tabs');
    nav.setAttribute('aria-label', 'Settings sections');
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
    if (!data) { content.append(node('p', 'Loading settings…')); return; }
    if (active === 'agents') { renderAgents(content); return; }
    // YouTube channels are not a generic catalog entry: they carry an OAuth grant, a channel
    // identity read back from Google, and their own connect/reconnect/disconnect lifecycle.
    // They lead the tab, and the catalog picker below gets its own heading so the two do not
    // read as one list.
    if (active === 'social') {
      renderYouTubeConnections(content, { api, notify: message });
      content.append(node('h3', 'Other accounts and e-mail'));
    }
    const row = node('div', '', 'settings-add');
    const picker = /** @type {HTMLSelectElement} */ (node('select'));
    picker.setAttribute('aria-label', 'Service to add');
    option(picker, '', 'Choose a service…');
    for (const [kind, spec] of Object.entries(data.catalog)) {
      if (spec.group === active) option(picker, kind, spec.label);
    }
    const add = node('button', 'Add connection', 'secondary');
    add.addEventListener('click', () => {
      if (picker.value) edit(content, picker.value, null);
      else message('Choose a service first.', true);
    });
    row.append(picker, add);
    content.append(row);
    if (active === 'llm') renderLegacyProviders(content);
    const items = data.integrations.filter(item => data.catalog[item.kind].group === active);
    if (!items.length) content.append(node('p', 'You have not added any connection from the catalogue in this section yet.', 'helper'));
    const list = node('div', '', 'settings-connections');
    for (const item of items) {
      const spec = data.catalog[item.kind];
      const card = node('article', '', 'settings-card');
      card.append(node('h3', item.name), node('p', `${spec.label} · ${statuses[item.status] || item.status}`, 'helper'));
      if (item.checked_at) card.append(node('p', `Verified: ${new Date(item.checked_at).toLocaleString('en-GB')}`, 'helper'));
      // Three different truths, and the card says which one applies. "stored" means the
      // credentials are kept but nothing in the pipeline calls this vendor yet; "media" means
      // it will be called, but only once it is verified and selected for a purpose.
      if (spec.runtime === 'stored') {
        card.append(node('p', 'Details saved. Use in the pipeline is not available yet.', 'settings-limitation'));
      } else if (spec.runtime === 'media' && item.status !== 'ACCESS_VERIFIED' && item.status !== 'VERIFIED') {
        card.append(node('p', 'Verify access, then select the service below for the purpose you want. Until then renders use substitutes, and QC blocks them from publishing.', 'settings-limitation'));
      }
      const actions = node('div', '', 'settings-actions');
      const modify = node('button', 'Edit', 'quiet');
      modify.addEventListener('click', () => edit(content, item.kind, item));
      actions.append(modify);
      const check = node('button', spec.runtime === 'llm' ? 'Verify and load models' : 'Verify access', 'secondary');
      check.addEventListener('click', () => run(() => api(`/settings/integrations/${item.id}/check`, { method: 'POST' }), 'Verification finished.'));
      actions.append(check);
      const remove = node('button', 'Delete connection', 'quiet');
      remove.addEventListener('click', () => {
        if (remove.dataset.armed !== 'yes') {
          remove.dataset.armed = 'yes';
          remove.textContent = 'Confirm deletion';
          return;
        }
        run(() => api(`/settings/integrations/${item.id}?expected_version=${item.version}`, { method: 'DELETE' }), 'Connection deleted.');
      });
      actions.append(remove);
      card.append(actions);
      // A connection with a discovered catalog (the backend decides which kinds) gets the
      // production defaults section; the labels come with the catalog.
      if (data.provider_catalogs?.[item.id]) {
        renderProviderProduction(card, item, data.provider_catalogs[item.id], { api, run });
      }
      list.append(card);
    }
    content.append(list);
    if (active === 'media') renderAutoConfigure(content);
    if (active === 'media' || active === 'social') renderSelections(content, items);
    if (active === 'social' && data.legacy_youtube_configured) content.append(node('p', 'There is also a YouTube configuration in the server environment. A YouTube selection saved here takes priority.', 'helper'));
  }

  function edit(container, kind, existing) {
    container.querySelector('.settings-editor')?.remove();

    const spec = data.catalog[kind];
    const form = /** @type {HTMLFormElement} */ (node('form', '', 'settings-editor'));
    form.append(node('h3', `${existing ? 'Edit' : 'Add'} · ${spec.label}`));
    const hint = node('p', spec.help, 'helper');
    const docs = /** @type {HTMLAnchorElement} */ (node('a', 'Open the service documentation'));
    docs.href = spec.docs;
    docs.target = '_blank';
    docs.rel = 'noopener noreferrer';
    form.append(hint, docs);
    const grid = node('div', '', 'settings-fields');
    const fields = [{ key: 'name', label: 'Connection name', kind: 'text', required: true, secret: false, choices: [] }, ...spec.fields];
    for (const field of fields) {
      const label = node('label', field.label);
      let input;
      if (field.choices.length) {
        input = /** @type {HTMLSelectElement} */ (node('select'));
        option(input, '', 'Choose…');
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
      if (field.secret && existing?.secret_fields.includes(field.key)) label.append(node('small', 'Saved. Leave empty to keep the key.', 'helper'));
      grid.append(label);
    }
    form.append(grid, node('p', 'Keys are encrypted on the server. They are never shown again after saving.', 'helper'));
    const save = /** @type {HTMLButtonElement} */ (node('button', 'Save connection', 'primary'));
    save.type = 'submit';
    const cancel = /** @type {HTMLButtonElement} */ (node('button', 'Cancel', 'quiet'));
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
      }, 'Connection saved. Verify access before use.');
    });
    container.prepend(form);
    form.querySelector('input')?.focus();
  }

  /**
   * One action for what a verified connection leaves unfinished: the service for a purpose
   * with a single candidate, and the defaults that are still empty. It reports every choice
   * with its reason, and changes nothing that was already chosen. The report survives the
   * reload that follows, because the reload is what shows those choices taking effect.
   */
  function renderAutoConfigure(container) {
    const box = node('div', '', 'settings-autoconfig');
    // The stewards read their vendors' pages and choose; the lines they report join the
    // same list the auto-configure report uses, so both show after the reload.
    const research = node('button', 'Model research now (Kael and Lyra read the documentation)', 'secondary');
    research.title = 'The stewards read the pages of the connected providers, note prices and capabilities, and choose the default model wherever you have not locked it. It takes a few minutes.';
    research.addEventListener('click', () => run(async () => {
      const result = await api('/settings/model-research', { method: 'POST' });
      autoConfigReport = Object.values(result).map((r) => r.status === 'COMPLETED'
        ? `${r.purpose}: ${r.steward} recommends ${r.recommended || '—'}${r.changed ? ' (set as default)' : ''}${r.reason ? ` — ${r.reason}` : ''}`
        : `${r.purpose}: ${r.reason}`);
      return { message: 'Model research finished.' };
    }, 'Model research finished.'));
    const button = node('button', 'Configure services and defaults automatically', 'secondary');
    button.addEventListener('click', () => run(async () => {
      const result = await api('/settings/auto-configure', { method: 'POST' });
      autoConfigReport = [
        ...(result.applied || []).map(item => `${item.purpose}: ${item.connection} — ${item.why}`),
        ...(result.ambiguous || []).map(item => `${item.purpose}: ${item.why} (${(item.candidates || []).join(', ')})`),
      ];
      return { message: autoConfigReport.length ? `${(result.applied || []).length} filled in.` : 'Nothing to fill in: everything was already chosen.' };
    }, 'Configuration applied.'));
    box.append(
      node('p', 'You connected the providers, but production also needs a choice per purpose (Images, Video, Voice) and default values. The button chooses only where there is a single candidate and fills in only what is empty; you can change anything on the connection card. Model research goes further: the stewards read the provider documentation and choose on evidence.', 'helper'),
      node('div', '', 'settings-autoconfig-actions'),
    );
    box.querySelector('.settings-autoconfig-actions').append(button, research);
    if (autoConfigReport.length) {
      const list = node('ul', '', 'settings-autoconfig-list');
      for (const line of autoConfigReport) list.append(node('li', line));
      box.append(list);
    }
    container.append(box);
  }

  function renderSelections(container, items) {
    const available = Object.entries(purposes).filter(([purpose]) => items.some(item => [...data.catalog[item.kind].purposes, item.kind].includes(purpose)));
    if (!available.length) return;
    container.append(node('h3', active === 'media' ? 'Services chosen for production' : 'Chosen accounts'));
    for (const [purpose, label] of available) {
      const row = node('div', '', 'settings-routing');
      const select = /** @type {HTMLSelectElement} */ (node('select'));
      select.setAttribute('aria-label', label);
      option(select, '', 'No selection');
      for (const item of items) if ([...data.catalog[item.kind].purposes, item.kind].includes(purpose)) option(select, item.id, item.name);
      select.value = data.selections[purpose]?.integration_id || '';
      const save = node('button', 'Apply', 'secondary');
      save.addEventListener('click', () => {
        run(() => api(`/settings/selections/${purpose}`, { method: 'PUT', body: JSON.stringify({ integration_id: select.value || null, expected_version: data.selections[purpose]?.version || 0 }) }), 'Selection saved.');
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
            ? `Verified: ${new Date(provider.last_health_check).toLocaleString('en-GB')}`
            : 'Added automatically at installation. It has never been contacted, so its models cannot be assigned yet.',
          verified ? 'helper' : 'settings-limitation',
        ),
      );
      const actions = node('div', '', 'settings-actions');
      const check = node('button', 'Verify and load models', 'secondary');
      check.addEventListener('click', () => {
        run(async () => {
          const result = await api(`/providers/${provider.id}/sync-models`, { method: 'POST' });
          const available = (result.models || []).filter(model => model.is_available).length;
          return {
            message: available
              ? `${provider.name} answered: ${available} models available.`
              : `${provider.name} answered, but offers no model.`,
          };
        }, '');
      });
      actions.append(check);
      card.append(actions);
      container.append(card);
    }
  }

  function renderAgents(container) {
    container.append(node('p', 'Add and verify an AI provider, then assign a model to each agent. The test runs one real request through the assigned model.', 'helper'));
    if (!data.agents.length) container.append(node('p', 'There are no agents in the studio yet.'));
    for (const agent of data.agents) {
      const card = node('article', '', 'settings-card');
      const role = data.roles.find(role => role.id === agent.role_id);
      card.append(node('h3', agent.display_name), node('p', role?.name || 'Unidentified role', 'helper'));
      const named = id => data.models.find(model => model.id === id)?.model_name;
      const current = data.models.find(model => model.id === agent.model_id);
      card.append(node('p', `Current model: ${current?.model_name || 'Unknown'}`, 'helper'));
      const extra = [named(agent.secondary_model_id), named(agent.tertiary_model_id)].filter(Boolean);
      card.append(
        node(
          'p',
          extra.length
            ? `${agent.multi_llm_strategy} with ${extra.join(' and ')} · ${agent.additional_llm_policy}`
            : 'A single model (SINGLE)',
          'helper',
        ),
      );
      // Three slots and a strategy, on the card that already existed. A model is a
      // configuration value here and nowhere else: the studio's logic never reads its name,
      // so any of the three can be replaced tomorrow without touching code.
      const usable = data.models.filter(
        model =>
          model.is_available &&
          (role?.required_capabilities || []).every(cap => model.capabilities.includes(cap)),
      );
      const modelSelect = (label, value, withNone) => {
        const select = /** @type {HTMLSelectElement} */ (node('select'));
        select.setAttribute('aria-label', `${label} for ${agent.display_name}`);
        option(select, '', withNone ? 'None' : 'Choose an available model…');
        for (const model of usable) {
          const connection = data.integrations.find(item => item.id === model.provider_id);
          option(select, model.id, `${connection?.name || 'Existing provider'} · ${model.model_name}`);
        }
        select.value = value || '';
        return select;
      };
      const select = modelSelect('Primary model', agent.model_id, false);
      const secondary = modelSelect('Secondary model', agent.secondary_model_id, true);
      const tertiary = modelSelect('Tertiary model', agent.tertiary_model_id, true);
      const strategy = /** @type {HTMLSelectElement} */ (node('select'));
      strategy.setAttribute('aria-label', `Strategy for ${agent.display_name}`);
      for (const [value, text] of [
        ['SINGLE', 'Single — the primary model only'],
        ['FALLBACK', 'Fallback — the second takes over if the first does not answer'],
        ['REVIEW', 'Review — the second critiques, the first decides'],
        ['DEBATE', 'Debate — they answer independently, the agent reconciles'],
        ['PARALLEL', 'Parallel — they work in parallel, the agent synthesises'],
      ]) option(strategy, value, text);
      strategy.value = agent.multi_llm_strategy || 'SINGLE';
      const policy = /** @type {HTMLSelectElement} */ (node('select'));
      policy.setAttribute('aria-label', `When the extra models are used for ${agent.display_name}`);
      for (const [value, text] of [
        ['IMPORTANT_ONLY', 'Only for important tasks'],
        ['LOW_CONFIDENCE', 'When confidence is low'],
        ['ALWAYS', 'Always'],
        ['MANUAL', 'Only on explicit request'],
      ]) option(policy, value, text);
      policy.value = agent.additional_llm_policy || 'IMPORTANT_ONLY';
      const importance = /** @type {HTMLSelectElement} */ (node('select'));
      importance.setAttribute('aria-label', `Importance threshold for ${agent.display_name}`);
      for (const [value, text] of [
        ['ROUTINE', 'Threshold: any task'],
        ['NOTABLE', 'Threshold: notable tasks'],
        ['STRATEGIC', 'Threshold: strategic decisions only'],
      ]) option(importance, value, text);
      importance.value = agent.min_importance || 'STRATEGIC';
      card.append(
        node('p', 'Primary model', 'helper'), select,
        node('p', 'Secondary model (critic, fallback or peer)', 'helper'), secondary,
        node('p', 'Tertiary model (arbiter)', 'helper'), tertiary,
        node('p', 'How they work together', 'helper'), strategy,
        node('p', 'When the extra models are worth it', 'helper'), policy,
        importance,
      );
      const save = node('button', 'Save assignment', 'secondary');
      save.addEventListener('click', () => {
        if (!select.value) { message('Choose a model that is available and fits the role.', true); return; }
        if (strategy.value !== 'SINGLE' && !secondary.value) {
          message('The chosen strategy needs a second model.', true);
          return;
        }
        if (tertiary.value && !secondary.value) {
          message('A third model without a second has no one to critique.', true);
          return;
        }
        run(() => api(`/settings/agents/${agent.id}/model`, {
          method: 'PUT',
          body: JSON.stringify({
            model_id: select.value,
            expected_version: agent.version,
            secondary_model_id: secondary.value || null,
            tertiary_model_id: tertiary.value || null,
            multi_llm_strategy: strategy.value,
            additional_llm_policy: policy.value,
            min_importance: importance.value,
          }),
        }), 'Assignment saved.');
      });
      const test = node('button', 'Test the answer', 'secondary');
      test.addEventListener('click', () => {
        run(async () => {
          const result = await api(`/settings/agents/${agent.id}/test`, { method: 'POST' });
          const text = String(result.output_text || '').replace(/\s+/g, ' ').trim();
          if (result.status === 'SUCCEEDED') {
            return text
              ? { message: `${result.model_name} answered: “${text.slice(0, 140)}”` }
              : { message: 'The model ran (tokens counted) but produced no visible text — raise the budget or try another model.' };
          }
          throw new Error(`The test did not run: ${result.status}${result.error_detail ? ` — ${result.error_detail}` : ''}`);
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
