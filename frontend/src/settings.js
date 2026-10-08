import { renderYouTubeConnections } from './youtube_connections.js';
import { icon } from './icons.js';
import { renderProviderProduction } from './provider_production.js';
import { connectionTitle, policyWord, providerName } from './dialog_words.js';
import {
  DIRECTOR_RIGHT_LABEL, MODULE_STATE, channelFacts, directorRightAnswer, directorRightCommand,
  directorRightConfirmKey, directorRightLines, directorRightQuestion, modulesSummary, SERIAL_CHANNEL_TYPE,
  PRIVACY_CHOICES, publishPolicyAnswer, publishPolicyCommand, publishPolicyQuestion, publishPolicyWords,
} from './owner_controls.js';
import { countWords } from './plurals.js';

import './settings.css';

// W34: «Canale» holds the Owner's decisions about each channel (the Director's right to approve the
// serial's episodes); «Despre studio» the module list that left the main screen
const sections = [['llm', 'Furnizori AI'], ['agents', 'Angajați'], ['media', 'Video și sunet'], ['social', 'Conturi și e-mail'], ['channels', 'Canale'], ['about', 'Despre studio']];

/** The module names the drawer gave them (main.js), for Setări → Despre studio. */
const MODULE_LABEL = {
  agents: 'Angajați', providers: 'Furnizori AI', workflows: 'Automatizare', research: 'Cercetare factuală',
  media: 'Producție media', publishing: 'Publicare', story: 'Office Serial',
 settings: 'Setări', analytics: 'Analitice',
};
// No 'youtube' purpose: a YouTube channel is chosen by connecting it, not by picking a saved
// credential row out of a list. The backend refuses that purpose for the same reason.
const purposes = { image: 'Imagini', video: 'Video', voice: 'Voce / TTS', music: 'Muzică / sunet', tiktok: 'TikTok', instagram: 'Instagram', facebook: 'Facebook', email: 'E-mail' };
const statuses = { SAVED: 'Salvat · neverificat', VERIFIED: 'Conexiune verificată', ACCESS_VERIFIED: 'Acces verificat · flux în așteptare', FAILED: 'Verificare eșuată' };

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
 * @param {{ onChange?: () => Promise<void> | void, modules?: () => Record<string, string> | null, onAutonomy?: () => void }} [hooks]
 *   `onChange` runs after every successful change here. Assigning a model, verifying a
 *   provider or binding a channel all alter what the rest of the app should be showing —
 *   the office inspector in particular — and without this the app kept displaying the state
 *   from before the change until the page was reloaded.
 */
export function initSettings(api, hooks = {}) {
  // The page heading is gone; the Settings button lives in the top bar with the session.
  const heading = document.querySelector('.topbar-right') || document.querySelector('#workspace');
  const open = node('button', 'Setări', 'secondary');
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
  const connectionChecks = new Map();
  

  function reset() {
    generation++;
    data = null;
    pending = false;
    connectionChecks.clear();
    channels = null;
    channelsError = '';
    asking = null;
    answer = null;
    policyAsking = null;
    policyAnswer = null;

    dialog.close();
    // W28: the door goes back into its room with its words fading, not as an empty pane; what
    // it held is cleared once it has left (a new opening builds it again in render()).
    const gen = generation;
    window.setTimeout(() => { if (!dialog.open && gen === generation) dialog.replaceChildren(); }, 400);
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

  /** @param {Function} operation @param {string} success @param {{connectionId?: string}} [options] */
  async function run(operation, success, options = {}) {
    if (pending) return;
    pending = true;
    const current = generation;
    if (options.connectionId) {
      connectionChecks.set(options.connectionId, { status: 'CHECKING', message: 'Se verifică accesul și se încarcă modelele…' });
      render();
      message('Se verifică conexiunea…');
    }
    dialog.querySelectorAll('button, input, select').forEach(el => { /** @type {HTMLButtonElement} */ (el).disabled = true; });
    try {
      const result = await operation();
      if (current !== generation) return;
      if (options.connectionId) connectionChecks.set(options.connectionId, result);
      await refresh();
      try {
        await hooks.onChange?.();
      } catch {
        // Telling the rest of the app is best effort; the change itself already succeeded.
      }
      message(result?.message || success, result?.status === 'FAILED' || result?.discovery_status === 'ERROR');
    } catch (error) {
      if (current === generation) {
        if (options.connectionId) {
          connectionChecks.set(options.connectionId, { status: 'FAILED', message: error.message });
          render();
        }
        message(error.message, true);
      }
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
    const title = node('h2', 'Setări', 'dialog-title');
    title.id = 'settings-title';
    // The room's eyebrow, as the other seven doors carry theirs (glossary W26).
    const heading = node('div');
    heading.append(node('p', 'STUDIO · CONEXIUNI', 'eyebrow dialog-eyebrow'), title);
    const close = node('button', '', 'dialog-close');
  close.innerHTML = icon('close');
  close.setAttribute('aria-label', 'Închide');
    close.setAttribute('aria-label', 'Închide');
    close.title = 'Închide';
    close.addEventListener('click', reset);
    header.append(heading, close);
    dialog.append(header, node('p', 'Conectează doar serviciile pe care vrei să le folosească studioul.', 'settings-intro'));
    const nav = node('nav', '', 'settings-tabs');
    nav.setAttribute('aria-label', 'Secțiunile setărilor');
    for (const [key, label] of sections) {
      const button = node('button', label, key === active ? 'primary' : 'quiet');
      button.setAttribute('aria-current', key === active ? 'page' : 'false');
      button.addEventListener('click', () => { active = key; render(); });
      nav.append(button);
    }
    const autonomy = node('button', 'Autonomie · programare și buget', 'secondary');
    autonomy.addEventListener('click', () => { reset(); hooks.onAutonomy?.(); });
    dialog.append(autonomy, nav);
    const output = node('p', '', 'settings-message');
    output.setAttribute('role', 'status');
    dialog.append(output);
    const content = node('section', '', 'settings-content');
    dialog.append(content);
    if (active === 'about') { renderAbout(content); return; }
    if (active === 'channels') { renderChannels(content); return; }
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
    option(picker, '', 'Alege un serviciu…');
    for (const [kind, spec] of Object.entries(data.catalog)) {
      if (spec.group === active) option(picker, kind, spec.label);
    }
    const add = node('button', 'Adaugă conexiunea', 'secondary');
    add.addEventListener('click', () => {
      if (picker.value) edit(content, picker.value, null);
      else message('Alege întâi un serviciu.', true);
    });
    row.append(picker, add);
    content.append(row);
    const items = data.integrations.filter(item => data.catalog[item.kind].group === active);
    // One grid, not two stacked. Appended straight onto the section, the providers
    // that predate this screen sat one per row while the catalogue's cards beside
    // them shared three columns; kept in separate grids they left the last card of
    // the first one stranded across the full width. Same card, same grid, in order.
    const list = node('div', '', 'settings-connections');
    if (active === 'llm') renderLegacyProviders(list);
    for (const item of items) {
      const spec = data.catalog[item.kind];
      const card = node('article', '', 'settings-card');
      // W32: a stored name that is a machine identifier («settings:<uuid>») is its title only; the
      // whole name stays in the title's tooltip, not printed as a line of its own
      const named = connectionTitle(item.name, spec.label);
      const heading = node('h3', named.title);
      if (named.identifier) heading.title = item.name;
      card.append(heading);
      const checkResult = connectionChecks.get(item.id) || item.check_result;
      const oldCloudCheck = item.kind === 'ollama' && hostOf(item.config?.base_url) === 'ollama.com'
        && item.status === 'VERIFIED' && !checkResult;
      const state = oldCloudCheck ? 'Catalog încărcat · cheia netestată' : (statuses[item.status] || item.status);
      card.append(node('p', `${spec.label} · ${state}`, 'helper'));
      if (checkResult?.message) {
        const report = node('p', checkResult.message, 'settings-check-result');
        report.classList.toggle('settings-error', checkResult.status === 'FAILED' || checkResult.discovery_status === 'ERROR');
        report.dataset.status = checkResult.status;
        report.setAttribute('role', 'status');
        card.append(report);
      }
      if (item.checked_at) card.append(node('p', `Verificat: ${new Date(item.checked_at).toLocaleString('ro-RO')}`, 'helper'));
      // Three different truths, and the card says which one applies. "stored" means the
      // credentials are kept but nothing in the pipeline calls this vendor yet; "media" means
      // it will be called, but only once it is verified and selected for a purpose.
      if (spec.runtime === 'stored') {
        card.append(node('p', 'Detaliile sunt salvate. Folosirea în flux nu este încă disponibilă.', 'settings-limitation'));
      } else if (spec.runtime === 'media' && item.status !== 'ACCESS_VERIFIED' && item.status !== 'VERIFIED') {
        card.append(node('p', 'Verifică accesul, apoi alege mai jos serviciul pentru scopul dorit. Până atunci randările folosesc substitute, iar QC le blochează de la publicare.', 'settings-limitation'));
      }
      const actions = node('div', '', 'settings-actions');
      const modify = node('button', 'Modifică', 'quiet');
      modify.addEventListener('click', () => edit(content, item.kind, item));
      actions.append(modify);
      const check = node('button', spec.runtime === 'llm' ? 'Verifică și încarcă modelele' : 'Verifică accesul', 'secondary');
      check.addEventListener('click', () => run(() => api(`/settings/integrations/${item.id}/check`, { method: 'POST' }), 'Verificarea s-a încheiat.', { connectionId: item.id }));
      actions.append(check);
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
      // A connection with a discovered catalog (the backend decides which kinds) gets the
      // production defaults section; the labels come with the catalog.
      if (data.provider_catalogs?.[item.id]) {
        renderProviderProduction(card, item, data.provider_catalogs[item.id], { api, run });
      }
      list.append(card);
    }
    content.append(list);
    // The sentence is about the catalogue, so it follows the cards rather than
    // standing above the providers that predate the catalogue entirely.
    if (!items.length) content.append(node('p', 'Nu ai adăugat încă nicio conexiune din catalog în această secțiune.', 'helper'));
    if (active === 'media') renderAutoConfigure(content);
    if (active === 'media' || active === 'social') renderSelections(content, items);
    if (active === 'social' && data.legacy_youtube_configured) content.append(node('p', 'Există și o configurație YouTube în mediul serverului. O selecție YouTube salvată aici are prioritate.', 'helper'));
  }

  /**
   * A stored name that is really a machine identifier, read as two things.
   *
   * The installer writes connections named "<what made it>:<uuid>". Printed whole at
   * heading weight that is the loudest thing on the screen and it says nothing. The
   * word before the identifier is the title; the whole name is kept for the title's tooltip
   * (W32: no longer printed as a line of its own under the title). A name with
   * no identifier in it comes back unchanged and nothing below it is drawn.
   *
   * @param {string} name @returns {{title: string, identifier: string}}
   */
  /** @param {unknown} url the host of a provider's address, or the address as written */
  function hostOf(url) {
    try { return new URL(String(url)).host || String(url); } catch { return String(url ?? ''); }
  }

  function edit(container, kind, existing) {
    container.querySelector('.settings-editor')?.remove();

    const spec = data.catalog[kind];
    const form = /** @type {HTMLFormElement} */ (node('form', '', 'settings-editor'));
    form.append(node('h3', `${existing ? 'Modifică' : 'Adaugă'} · ${spec.label}`));
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
      if (field.secret && existing?.secret_fields.includes(field.key)) label.append(node('small', 'Salvată. Lasă gol ca să păstrezi cheia.', 'helper'));
      grid.append(label);
    }
    form.append(grid, node('p', 'Cheile sunt criptate pe server. După salvare nu mai sunt arătate niciodată.', 'helper'));
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
        try {
          const result = await api(`/settings/integrations/${identifier}`, { method: 'PUT', body: JSON.stringify(payload) });
          connectionChecks.delete(identifier);
          return result;
        }
        finally { form.querySelectorAll('input[type=password]').forEach(input => { /** @type {HTMLInputElement} */ (input).value = ''; }); }
      }, 'Conexiune salvată. Verifică accesul înainte de folosire.');
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
    const research = node('button', 'Cercetare de modele acum (Kael și Lyra citesc documentația)', 'secondary');
    research.title = 'Responsabilii citesc paginile furnizorilor conectați, notează prețuri și capabilități și aleg modelul implicit acolo unde nu l-ai blocat. Durează câteva minute.';
    research.addEventListener('click', () => run(async () => {
      const result = await api('/settings/model-research', { method: 'POST' });
      autoConfigReport = Object.values(result).map((r) => r.status === 'COMPLETED'
        ? `${r.purpose}: ${r.steward} recomandă ${r.recommended || '—'}${r.changed ? ' (setat ca implicit)' : ''}${r.reason ? ` — ${r.reason}` : ''}`
        : `${r.purpose}: ${r.reason}`);
      return { message: 'Cercetarea de modele s-a încheiat.' };
    }, 'Cercetarea de modele s-a încheiat.'));
    const button = node('button', 'Configurează automat serviciile și valorile implicite', 'secondary');
    button.addEventListener('click', () => run(async () => {
      const result = await api('/settings/auto-configure', { method: 'POST' });
      autoConfigReport = [
        ...(result.applied || []).map(item => `${item.purpose}: ${item.connection} — ${item.why}`),
        ...(result.ambiguous || []).map(item => `${item.purpose}: ${item.why} (${(item.candidates || []).join(', ')})`),
      ];
      return { message: autoConfigReport.length ? `${(result.applied || []).length} completate.` : 'Nimic de completat: totul era deja ales.' };
    }, 'Configurația a fost aplicată.'));
    box.append(
      node('p', 'Ai conectat furnizorii, dar producția are nevoie și de o alegere pe fiecare scop (Imagini, Video, Voce) și de valori implicite. Butonul alege numai unde există un singur candidat și completează numai ce este gol; poți schimba orice pe cardul conexiunii. Cercetarea de modele merge mai departe: responsabilii citesc documentația furnizorului și aleg pe bază de dovezi.', 'helper'),
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
    container.append(node('h3', active === 'media' ? 'Servicii alese pentru producție' : 'Conturi alese'));
    for (const [purpose, label] of available) {
      const row = node('div', '', 'settings-routing');
      const select = /** @type {HTMLSelectElement} */ (node('select'));
      select.setAttribute('aria-label', label);
      option(select, '', 'Nicio selecție');
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
      // W33: the seed's «settings:<uuid>» is titled by the service and its host, not «settings»
      const named = connectionTitle(provider.name, `${providerName(provider.provider_type)} · ${hostOf(provider.base_url)}`);
      const heading = node('h3', named.title);
      if (named.identifier) heading.title = provider.name;
      card.append(heading);
      // W27: the seed wrote the type as «OLLAMA» on one card and «ollama» on the next; both are Ollama
      card.append(node('p', `${providerName(provider.provider_type)} · ${provider.base_url}`, 'helper'));
      card.append(
        node(
          'p',
          verified
            ? `Verificat: ${new Date(provider.last_health_check).toLocaleString('ro-RO')}`
            : 'Adăugat automat la instalare. Nu a fost contactat niciodată, deci modelele lui nu pot fi încă alocate.',
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
              ? `${provider.name} a răspuns: ${countWords(available, 'model disponibil', 'modele disponibile')}.`
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
    container.append(node('p', 'Adaugă și verifică un furnizor AI, apoi alocă un model fiecărui angajat. Testul trimite o cerere reală prin modelul alocat.', 'helper'));
    if (!data.agents.length) container.append(node('p', 'Nu există încă angajați în studio.'));
    // An agent's card carries four pickers, so its grid takes a wider track than
    // the connection cards' — two columns on a 1000px dialog, never four cramped ones.
    const grid = node('div', '', 'settings-connections settings-agent-grid');
    container.append(grid);
    container = grid;
    for (const agent of data.agents) {
      const card = node('article', '', 'settings-card');
      const role = data.roles.find(role => role.id === agent.role_id);
      card.append(node('h3', agent.display_name), node('p', role?.name || 'Rol neidentificat', 'helper'));
      const named = id => data.models.find(model => model.id === id)?.model_name;
      const current = data.models.find(model => model.id === agent.model_id);
      card.append(node('p', `Model curent: ${current?.model_name || 'necunoscut'}`, 'helper'));
      const extra = [named(agent.secondary_model_id), named(agent.tertiary_model_id)].filter(Boolean);
      card.append(
        node(
          'p',
          extra.length
            ? `${agent.multi_llm_strategy} cu ${extra.join(' și ')} · ${policyWord(agent.additional_llm_policy)}`
            : 'Un singur model (SINGLE)',
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
        select.setAttribute('aria-label', `${label} pentru ${agent.display_name}`);
        option(select, '', withNone ? 'Niciunul' : 'Alege un model disponibil…');
        for (const model of usable) {
          const connection = data.integrations.find(item => item.id === model.provider_id);
          option(select, model.id, `${connection?.name || 'Furnizor existent'} · ${model.model_name}`);
        }
        select.value = value || '';
        return select;
      };
      const select = modelSelect('Model principal', agent.model_id, false);
      const secondary = modelSelect('Model secundar', agent.secondary_model_id, true);
      const tertiary = modelSelect('Model terțiar', agent.tertiary_model_id, true);
      const strategy = /** @type {HTMLSelectElement} */ (node('select'));
      strategy.setAttribute('aria-label', `Strategie pentru ${agent.display_name}`);
      for (const [value, text] of [
        ['SINGLE', 'SINGLE — numai modelul principal'],
        ['FALLBACK', 'FALLBACK — al doilea preia dacă primul nu răspunde'],
        ['REVIEW', 'REVIEW — al doilea critică, primul decide'],
        ['DEBATE', 'DEBATE — răspund independent, angajatul împacă'],
        ['PARALLEL', 'PARALLEL — lucrează în paralel, angajatul sintetizează'],
      ]) option(strategy, value, text);
      strategy.value = agent.multi_llm_strategy || 'SINGLE';
      const policy = /** @type {HTMLSelectElement} */ (node('select'));
      policy.setAttribute('aria-label', `Când se folosesc modelele suplimentare pentru ${agent.display_name}`);
      for (const [value, text] of [
        ['IMPORTANT_ONLY', 'Numai pentru sarcini importante'],
        ['LOW_CONFIDENCE', 'Când încrederea este scăzută'],
        ['ALWAYS', 'Întotdeauna'],
        ['MANUAL', 'Numai la cerere explicită'],
      ]) option(policy, value, text);
      policy.value = agent.additional_llm_policy || 'IMPORTANT_ONLY';
      const importance = /** @type {HTMLSelectElement} */ (node('select'));
      importance.setAttribute('aria-label', `Pragul de importanță pentru ${agent.display_name}`);
      for (const [value, text] of [
        ['ROUTINE', 'Prag: orice sarcină'],
        ['NOTABLE', 'Prag: sarcini notabile'],
        ['STRATEGIC', 'Prag: numai decizii strategice'],
      ]) option(importance, value, text);
      importance.value = agent.min_importance || 'STRATEGIC';
      card.append(
        node('p', 'Model principal', 'helper'), select,
        node('p', 'Model secundar (critic, rezervă sau egal)', 'helper'), secondary,
        node('p', 'Model terțiar (arbitru)', 'helper'), tertiary,
        node('p', 'Cum lucrează împreună', 'helper'), strategy,
        node('p', 'Când merită modelele suplimentare', 'helper'), policy,
        importance,
      );
      const save = node('button', 'Salvează alocarea', 'secondary');
      save.addEventListener('click', () => {
        if (!select.value) { message('Alege un model disponibil și potrivit rolului.', true); return; }
        if (strategy.value !== 'SINGLE' && !secondary.value) {
          message('Strategia aleasă are nevoie de un al doilea model.', true);
          return;
        }
        if (tertiary.value && !secondary.value) {
          message('Un al treilea model fără al doilea nu are pe cine să critice.', true);
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
        }), 'Alocare salvată.');
      });
      const test = node('button', 'Testează răspunsul', 'secondary');
      test.addEventListener('click', () => {
        run(async () => {
          const result = await api(`/settings/agents/${agent.id}/test`, { method: 'POST' });
          const text = String(result.output_text || '').replace(/\s+/g, ' ').trim();
          if (result.status === 'SUCCEEDED') {
            return text
              ? { message: `${result.model_name} a răspuns: „${text.slice(0, 140)}”` }
              : { message: 'Modelul a rulat (tokenii au fost numărați), dar nu a produs text vizibil — mărește bugetul sau încearcă alt model.' };
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

  /**
   * W34, Setări → Despre studio: the module list the side drawer carried at full weight, as the
   * server reports it, with the drawer's three words.
   * @param {HTMLElement} container
   */
  function renderAbout(container) {
    const modules = hooks.modules?.() || null;
    container.append(node('h3', 'Starea modulelor'));
    container.append(node('p', 'Cât din fiecare parte a studioului este construit, așa cum o raportează serverul studioului.', 'helper'));
    if (!modules || !Object.keys(modules).length) { container.append(node('p', '—', 'helper')); return; }
    container.append(node('p', modulesSummary(modules), 'settings-about-summary'));
    const list = node('ul', '', 'modules settings-modules');
    for (const [name, status] of Object.entries(modules)) {
      const item = node('li', MODULE_LABEL[name] || name);
      item.dataset.status = String(status);
      const badge = node('span', MODULE_STATE[String(status)] || String(status), 'module-state');
      item.append(badge);
      list.append(item);
    }
    container.append(list);
  }

  /** What Setări → Canale read last, with the one confirmation open, if any. */
  let channels = /** @type {any[]|null} */ (null);
  let channelsError = '';
  let asking = /** @type {{id: string, on: boolean}|null} */ (null);
  let answer = /** @type {{text: string, error: boolean}|null} */ (null);

  async function loadChannels() {
    const current = generation;
    try {
      const result = await api('/publishing/channels');
      if (current !== generation || !dialog.open) return;
      channels = Array.isArray(result?.channels) ? result.channels : [];
      channelsError = '';
    } catch (error) {
      if (current !== generation) return;
      channels = null;
      channelsError = error instanceof Error ? error.message : String(error);
    }
    if (active === 'channels') render();
  }

  /**
   * W34, Setări → Canale: each channel with its facts in the page's words, and on the serial's
   * channel the Director's right as a switch. The switch never changes anything by itself: it asks,
   * and only the Owner's «Da» sends the versioned command. The answer is shown as the backend gave
   * it, a refusal in the backend's own sentence.
   * @param {HTMLElement} container
   */
  function renderChannels(container) {
    container.append(node('p', 'Canalele pe care publică studioul și deciziile despre ele care sunt numai ale tale.', 'helper'));
    if (channels === null && !channelsError) {
      container.append(node('p', 'Se încarcă canalele…', 'helper'));
      void loadChannels();
      return;
    }
    if (channelsError) { container.append(node('p', channelsError, 'settings-error')); return; }
    if (!channels || !channels.length) { container.append(node('p', 'Niciun canal de distribuție configurat.', 'helper')); return; }
    // W36: the decision first, as its own lit plate; then each channel as a plate of its facts, laid
    // side by side at their own height (a card is never stretched to its neighbour's).
    const serial = channels.find((c) => c && c.channel_type === SERIAL_CHANNEL_TYPE);
    if (serial) container.append(directorSwitch(serial));
    const grid = node('div', '', 'channel-plates');
    for (const channel of channels) {
      const facts = channelFacts(channel);
      const isSerial = channel.channel_type === SERIAL_CHANNEL_TYPE;
      const card = node('article', '', `channel-plate${isSerial ? ' is-serial' : ''}`);
      const head = node('div', '', 'channel-plate-head');
      const mark = node('span', '', 'channel-plate-mark');
      mark.setAttribute('aria-hidden', 'true');
      mark.innerHTML = icon(isSerial ? 'clapper' : 'shortform');
      head.append(mark, node('h3', String(channel.channel_name || '—'), 'channel-plate-name'));
      const facts_ = node('dl', '', 'channel-plate-facts');
      const fact = (/** @type {string} */ label, /** @type {string} */ value, /** @type {string} */ title = '') => {
        const row = node('div', '', 'channel-plate-fact');
        const dd = node('dd', value);
        if (title) { dd.title = title; dd.classList.add('has-title'); }
        row.append(node('dt', label), dd);
        facts_.append(row);
      };
      fact('Tip', facts.type, String(channel.channel_type || ''));
      fact('Cont YouTube', facts.account, facts.accountTitle);
      fact('Politica canalului', `versiunea ${facts.version}`);
      card.append(head, facts_, publishPolicyForm(channel));
      grid.append(card);
    }
    container.append(grid);
  }

  /**
   * W36: the Director's right as an illuminated plate: its mark, its name, a large switch that is
   * calm when OFF and lit in the page's accent when ON, what each state does and spends beside it
   * (the W34 sentence, as its two states), and the confirmation as a glass step. The switch never
   * changes anything by itself: only «Da» sends the channel's versioned command.
   * @param {any} channel
   */
  function directorSwitch(channel) {
    const on = Boolean(channel.director_may_approve_episodes);
    const facts = channelFacts(channel);
    const box = node('section', '', `decision-plate ${on ? 'is-on' : 'is-off'}${asking && asking.id === channel.id ? ' is-asking' : ''}`);
    box.setAttribute('aria-labelledby', 'director-right-title');
    const head = node('div', '', 'decision-head');
    const mark = node('span', '', 'decision-mark');
    mark.setAttribute('aria-hidden', 'true');
    mark.innerHTML = icon('seal');
    const words = node('div', '', 'decision-words');
    const eyebrow = node('p', `Decizia ta · ${String(channel.channel_name || '—')}`, 'decision-eyebrow');
    const title = node('h3', DIRECTOR_RIGHT_LABEL, 'decision-title');
    title.id = 'director-right-title';
    const version = node('p', `Politica canalului: versiunea ${facts.version}`, 'decision-version');
    words.append(eyebrow, title, version);
    const toggle = /** @type {HTMLButtonElement} */ (node('button', '', `decision-switch${on ? ' is-on' : ''}`));
    toggle.type = 'button';
    toggle.setAttribute('role', 'switch');
    toggle.setAttribute('aria-checked', on ? 'true' : 'false');
    toggle.setAttribute('aria-labelledby', 'director-right-title');
    toggle.id = 'director-right-switch';
    const track = node('span', '', 'decision-track');
    track.setAttribute('aria-hidden', 'true');
    track.append(node('span', '', 'decision-knob'));
    const state = node('span', on ? 'PORNIT' : 'OPRIT', 'decision-state');
    toggle.append(track, state);
    const lines = node('ul', '', 'decision-lines');
    lines.id = 'director-right-meaning';
    for (const line of directorRightLines(on)) {
      const li = node('li', '', `decision-line${line.now ? ' is-now' : ''}`);
      li.dataset.state = line.state;
      if (line.now) li.append(node('span', 'acum', 'decision-now'));
      li.append(document.createTextNode(line.text));
      lines.append(li);
    }
    toggle.setAttribute('aria-describedby', lines.id);
    toggle.addEventListener('click', () => {
      asking = { id: channel.id, on: !on };
      answer = null;
      render();
      /** @type {HTMLElement|null} */ (dialog.querySelector('.owner-confirm-yes'))?.focus();
    });
    head.append(mark, words, toggle);
    box.append(head, lines);
    if (asking && asking.id === channel.id) {
      const ask = node('div', '', 'owner-confirm decision-confirm');
      ask.setAttribute('role', 'group');
      ask.setAttribute('aria-label', directorRightQuestion(asking.on));
      const change = node('p', '', 'decision-change');
      change.append(
        node('span', 'Confirmă', 'decision-confirm-eyebrow'),
        node('span', on ? 'PORNIT' : 'OPRIT', `decision-chip ${on ? 'is-on' : 'is-off'}`),
        node('span', '→', 'decision-arrow'),
        node('span', asking.on ? 'PORNIT' : 'OPRIT', `decision-chip ${asking.on ? 'is-on' : 'is-off'}`),
      );
      ask.append(change, node('p', directorRightQuestion(asking.on), 'owner-confirm-question'));
      const keys = node('div', '', 'owner-confirm-keys');
      const yes = /** @type {HTMLButtonElement} */ (node('button', directorRightConfirmKey(asking.on), 'primary owner-confirm-yes'));
      yes.type = 'button';
      const no = /** @type {HTMLButtonElement} */ (node('button', 'Renunță', 'quiet'));
      no.type = 'button';
      const want = asking.on;
      no.addEventListener('click', () => {
        asking = null;
        render();
        /** @type {HTMLElement|null} */ (dialog.querySelector('#director-right-switch'))?.focus();
      });
      yes.addEventListener('click', async () => {
        yes.disabled = true;
        no.disabled = true;
        const current = generation;
        try {
          const result = await api(`/publishing/channels/${encodeURIComponent(channel.id)}/publish-policy`, {
            method: 'POST',
            body: JSON.stringify(directorRightCommand(channel, want, crypto.randomUUID())),
          });
          if (current !== generation) return;
          const words = directorRightAnswer(result);
          answer = words
            ? { text: words, error: false }
            : { text: 'Studioul nu a trimis un răspuns pe care pagina să-l poată citi. Reîncarcă și verifică starea.', error: true };
          if (result && result.channel) channels = (channels || []).map((c) => (c.id === channel.id ? { ...c, ...result.channel } : c));
        } catch (error) {
          if (current !== generation) return;
          answer = { text: error instanceof Error ? error.message : String(error), error: true };
          // a stale version is the backend's 409: the channels are read again, so the next try is current
          channels = null;
          void loadChannels();
        }
        asking = null;
        render();
        void hooks.onChange?.();
        /** @type {HTMLElement|null} */ (dialog.querySelector('#director-right-switch'))?.focus();
      });
      keys.append(yes, no);
      ask.append(keys, node('p', 'Până nu apeși Da, nu se schimbă nimic.', 'decision-confirm-note'));
      box.append(ask);
    }
    if (answer) {
      const said = node('p', answer.text, answer.error ? 'owner-answer settings-error' : 'owner-answer');
      said.setAttribute('role', 'status');
      box.append(said);
    }
    return box;
  }

  /**
   * PAGE-10 / PUB-11: what he typed in a channel's publish-policy form, kept across repaints, and
   * the one question or answer on screen. @type {Record<string, {privacy: string, publicAllowed: boolean, delay: string}>}
   */
  const policyDrafts = {};
  /** @type {{id: string, command: Record<string, unknown>, question: string}|null} */
  let policyAsking = null;
  /** @type {{id: string, text: string, error: boolean}|null} */
  let policyAnswer = null;

  /** @param {any} channel */
  function policyDraft(channel) {
    if (!policyDrafts[channel.id]) {
      policyDrafts[channel.id] = {
        privacy: String(channel.autonomous_privacy || 'private'),
        publicAllowed: Boolean(channel.public_publish_enabled),
        delay: String(Number(channel.publish_delay_minutes) || 0),
      };
    }
    return policyDrafts[channel.id];
  }

  /**
   * A channel's publish policy as a versioned form: the privacy of the studio's own uploads,
   * whether public is allowed at all, and the delay before a public release. Nothing is sent by
   * the form itself: «Schimbă politica» asks first, naming every change, and only «Da» sends the
   * channel's command. The backend's refusals (public while in TEST, a stale version) are shown
   * in its own words.
   * @param {any} channel
   */
  function publishPolicyForm(channel) {
    const id = String(channel.id);
    const draft = policyDraft(channel);
    const box = node('section', '', 'channel-policy');
    box.setAttribute('aria-labelledby', `policy-title-${id}`);
    const title = node('h4', 'Politica de publicare', 'channel-policy-title');
    title.id = `policy-title-${id}`;
    box.append(title, node('p', publishPolicyWords(channel), 'helper'));

    const privacyLabel = node('label', 'Vizibilitatea încărcărilor făcute singur de studio');
    privacyLabel.setAttribute('for', `policy-privacy-${id}`);
    const privacy = /** @type {HTMLSelectElement} */ (node('select', '', 'dialog-input'));
    privacy.id = `policy-privacy-${id}`;
    for (const [value, text] of PRIVACY_CHOICES) option(privacy, value, text);
    privacy.value = draft.privacy;
    privacy.addEventListener('change', () => { draft.privacy = privacy.value; });

    const allowedRow = node('label', '', 'channel-policy-check');
    allowedRow.setAttribute('for', `policy-public-${id}`);
    const allowed = /** @type {HTMLInputElement} */ (node('input'));
    allowed.type = 'checkbox';
    allowed.id = `policy-public-${id}`;
    allowed.checked = draft.publicAllowed;
    allowed.addEventListener('change', () => { draft.publicAllowed = allowed.checked; });
    allowedRow.append(allowed, document.createTextNode(' Publicul permis (numai în mediul PRODUCTION)'));

    const delayLabel = node('label', 'Întârzierea publicării publice, în minute');
    delayLabel.setAttribute('for', `policy-delay-${id}`);
    const delay = /** @type {HTMLInputElement} */ (node('input', '', 'dialog-input'));
    delay.id = `policy-delay-${id}`;
    delay.inputMode = 'numeric';
    delay.maxLength = 5;
    delay.value = draft.delay;
    delay.addEventListener('input', () => { draft.delay = delay.value; });

    const keys = node('div', '', 'settings-actions');
    const change = /** @type {HTMLButtonElement} */ (node('button', 'Schimbă politica', 'secondary'));
    change.type = 'button';
    change.addEventListener('click', () => {
      const built = publishPolicyCommand(channel, draft, crypto.randomUUID());
      if ('error' in built) {
        policyAsking = null;
        policyAnswer = { id, text: built.error, error: true };
      } else {
        policyAsking = { id, command: built.command, question: publishPolicyQuestion(channel, built.command) };
        policyAnswer = null;
      }
      render();
      /** @type {HTMLElement|null} */ (dialog.querySelector(`#policy-yes-${CSS.escape(id)}`))?.focus();
    });
    keys.append(change);
    box.append(privacyLabel, privacy, allowedRow, delayLabel, delay, keys);

    if (policyAsking && policyAsking.id === id) {
      const asked = policyAsking;
      const ask = node('div', '', 'owner-confirm decision-confirm');
      ask.setAttribute('role', 'group');
      ask.setAttribute('aria-label', asked.question);
      ask.append(node('p', asked.question, 'owner-confirm-question'));
      const answerKeys = node('div', '', 'owner-confirm-keys');
      const yes = /** @type {HTMLButtonElement} */ (node('button', 'Da, schimbă politica', 'primary owner-confirm-yes'));
      yes.type = 'button';
      yes.id = `policy-yes-${id}`;
      const no = /** @type {HTMLButtonElement} */ (node('button', 'Renunță', 'quiet'));
      no.type = 'button';
      no.addEventListener('click', () => { policyAsking = null; render(); });
      yes.addEventListener('click', async () => {
        yes.disabled = true;
        no.disabled = true;
        const current = generation;
        try {
          const result = await api(`/publishing/channels/${encodeURIComponent(id)}/publish-policy`, {
            method: 'POST',
            body: JSON.stringify(asked.command),
          });
          if (current !== generation) return;
          const words = publishPolicyAnswer(result);
          policyAnswer = words
            ? { id, text: words, error: false }
            : { id, text: 'Studioul nu a trimis un răspuns pe care pagina să-l poată citi. Reîncarcă și verifică starea.', error: true };
          if (result && result.channel) {
            channels = (channels || []).map((c) => (c.id === id ? { ...c, ...result.channel } : c));
            delete policyDrafts[id];
          }
        } catch (error) {
          if (current !== generation) return;
          // the backend's own sentence: public in TEST (422), a stale version or a reused id (409)
          policyAnswer = { id, text: error instanceof Error ? error.message : String(error), error: true };
          if (error && /** @type {any} */ (error).status === 409) {
            delete policyDrafts[id];
            channels = null;
            void loadChannels();
          }
        }
        policyAsking = null;
        render();
        void hooks.onChange?.();
      });
      answerKeys.append(yes, no);
      ask.append(answerKeys, node('p', 'Până nu apeși Da, nu se schimbă nimic.', 'decision-confirm-note'));
      box.append(ask);
    }
    if (policyAnswer && policyAnswer.id === id) {
      const said = node('p', policyAnswer.text, policyAnswer.error ? 'owner-answer settings-error' : 'owner-answer');
      said.setAttribute('role', 'status');
      box.append(said);
    }
    return box;
  }

  /** Open the door at a tab (W32: a preflight line's key opens the tab that fixes it). @param {string} [tab] */
  async function openAt(tab) {
    if (tab && sections.some(([key]) => key === tab)) active = tab;
    generation++;
    if (!dialog.open) dialog.showModal();
    render();
    try { await refresh(); } catch (error) { message(error.message, true); }
  }

  open.addEventListener('click', () => { void openAt(); });
  dialog.addEventListener('cancel', event => { event.preventDefault(); reset(); });
  return { reset, open: openAt };
}
