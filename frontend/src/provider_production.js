/**
 * Production defaults of a connection whose inventory was read from the vendor (ElevenLabs,
 * Runway, ...). Everything shown comes from the persisted catalog: the labels from
 * `kind_info`, the options from the discovered resources, never from authentication fields
 * and never from a list written here.
 */
export function renderProviderProduction(host, connection, catalog, { api, run }) {
  const node = (tag, text = '', className = '') => {
    const el = document.createElement(tag);
    el.textContent = text;
    el.className = className;
    return el;
  };
  const info = catalog?.kind_info || {};
  const hasVoices = info.has_voices === true;
  const section = node('section', '', 'provider-production');
  section.append(node('h4', info.title || 'Configurație de producție'));
  const state = catalog?.discovery;
  if (state?.last_success_at) {
    section.append(node('p', `Catalog actualizat: ${new Date(state.last_success_at).toLocaleString('ro-RO')}`, 'helper'));
  }
  if (state?.last_error) section.append(node('p', state.last_error, 'settings-limitation'));
  if (state?.status === 'SYNCING') section.append(node('p', info.syncing || 'Se încarcă catalogul…', 'helper'));
  if (state?.next_refresh_at) {
    section.append(node('p', `Următoarea actualizare automată: ${new Date(state.next_refresh_at).toLocaleString('ro-RO')}`, 'helper'));
  }
  const refresh = node('button', info.refresh_label || 'Actualizează catalogul', 'secondary');
  refresh.addEventListener('click', () => run(() => api(
    `/settings/integrations/${connection.id}/refresh-resources`, { method: 'POST' },
  ), 'Catalog actualizat.'));
  section.append(refresh);
  if (connection.status !== 'VERIFIED') {
    section.append(node('p', info.verify_hint || 'Verifică cheia ca să alegi valorile implicite.', 'helper'));
    host.append(section);
    return;
  }
  const production = catalog?.production || { model_id: null, voice_id: null, image_model_id: null, allow_production_override: true, version: 0 };
  section.append(node('p', hasVoices
    ? 'Modelul și vocea de mai jos sunt valorile implicite ale organizației: producția le folosește când niciun canal, serial, episod sau scenă nu alege altfel. Un personaj recurent cu identitate blocată are întotdeauna prioritate.'
    : 'Modelul de mai jos este valoarea implicită a organizației, doar o rezervă: producția îl folosește când niciun canal, serial, episod sau scenă nu alege alt model descoperit. Un personaj recurent cu look blocat acceptă numai modelele aprobate pentru el.', 'helper'));
  const fields = node('div', '', 'settings-fields');
  const picker = (label, resources, selected, purpose = null) => {
    const wrap = node('label', label);
    const select = document.createElement('select');
    select.setAttribute('aria-label', label);
    select.add(new Option('Nicio selecție', ''));
    for (const resource of resources) {
      const usable = purpose
        ? (resource.usable_purposes || []).includes(purpose)
        : resource.production_usable === true;
      const option = new Option(`${resource.name}${resource.name === resource.remote_id ? '' : ` · ${resource.remote_id}`}${usable ? '' : ` · ${info.unusable || 'indisponibil'}`}`, resource.remote_id);
      option.disabled = !usable;
      select.add(option);
    }
    select.value = resources.some(resource => resource.remote_id === selected) ? selected : '';
    wrap.append(select);
    if (!resources.length) wrap.append(node('small', 'API-ul nu a returnat nicio opțiune. Actualizează catalogul sau verifică permisiunile cheii.', 'helper'));
    if (selected && !resources.some(resource => resource.remote_id === selected && resource.production_usable)) {
      wrap.append(node('small', 'Selecția salvată nu mai este disponibilă; alege altă opțiune.', 'settings-limitation'));
    }
    fields.append(wrap);
    return select;
  };
  const purposes = info.purposes || [];
  const primary = hasVoices ? 'voice' : (purposes[0] || null);
  const model = picker(info.model_label || 'Model implicit', catalog?.models || [], production.model_id, primary);
  const voice = hasVoices ? picker(info.voice_label || 'Voce implicită', catalog?.voices || [], production.voice_id) : null;
  const imageModel = purposes.includes('image') && info.image_model_label
    ? picker(info.image_model_label, catalog?.models || [], production.image_model_id, 'image')
    : null;
  const overrideWrap = node('label', '', 'settings-toggle');
  const override = document.createElement('input');
  override.type = 'checkbox';
  override.checked = production.allow_production_override !== false;
  override.setAttribute('aria-label', 'Permite producției să suprascrie');
  overrideWrap.append(override, document.createTextNode(' Permite producției să suprascrie (canal, serial, episod, scenă)'));
  fields.append(overrideWrap);
  const save = node('button', 'Salvează valorile implicite', 'secondary');
  save.addEventListener('click', () => run(() => api(
    `/settings/integrations/${connection.id}/production`,
    { method: 'PUT', body: JSON.stringify({ model_id: model.value || null, voice_id: voice?.value || null,
      image_model_id: imageModel?.value || null,
      allow_production_override: override.checked, expected_version: production.version }) },
  ), 'Valori implicite salvate.'));
  section.append(fields, save);
  if (info.select_hint) section.append(node('p', info.select_hint, 'helper'));
  host.append(section);
}
