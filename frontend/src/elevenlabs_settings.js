/** Production choices from the persisted account inventory; never authentication fields. */
export function renderElevenLabsProduction(host, connection, catalog, { api, run }) {
  const node = (tag, text = '', className = '') => {
    const el = document.createElement(tag);
    el.textContent = text;
    el.className = className;
    return el;
  };
  const section = node('section', '', 'elevenlabs-production');
  section.append(node('h4', 'Configurație de producție · ElevenLabs'));
  const state = catalog?.discovery;
  if (state?.last_success_at) {
    section.append(node('p', `Catalog actualizat: ${new Date(state.last_success_at).toLocaleString('ro-RO')}`, 'helper'));
  }
  if (state?.last_error) section.append(node('p', state.last_error, 'settings-limitation'));
  if (state?.status === 'SYNCING') section.append(node('p', 'Se încarcă modelele și vocile…', 'helper'));
  if (state?.next_refresh_at) {
    section.append(node('p', `Următoarea actualizare automată: ${new Date(state.next_refresh_at).toLocaleString('ro-RO')}`, 'helper'));
  }
  const refresh = node('button', 'Actualizează modelele și vocile', 'secondary');
  refresh.addEventListener('click', () => run(() => api(
    `/settings/integrations/${connection.id}/refresh-resources`, { method: 'POST' },
  ), 'Catalog actualizat.'));
  section.append(refresh);
  if (connection.status !== 'VERIFIED') {
    section.append(node('p', 'Verifică cheia pentru a alege modelul și vocea de producție.', 'helper'));
    host.append(section);
    return;
  }
  const production = catalog?.production || { model_id: null, voice_id: null, allow_production_override: true, version: 0 };
  section.append(node('p', 'Modelul și vocea de mai jos sunt valorile implicite ale organizației: producția le folosește când niciun canal, serial, episod sau scenă nu alege altceva. Identitatea blocată a unui personaj recurent are întotdeauna prioritate.', 'helper'));
  const fields = node('div', '', 'settings-fields');
  const picker = (label, resources, selected, isModel) => {
    const wrap = node('label', label);
    const select = document.createElement('select');
    select.setAttribute('aria-label', label);
    select.add(new Option('Fără selecție', ''));
    for (const resource of resources) {
      const usable = resource.available && (!isModel || (
        resource.api_metadata.can_do_text_to_speech === true &&
        resource.capabilities.can_do_text_to_speech !== false
      ));
      const option = new Option(`${resource.name} · ${resource.remote_id}${usable ? '' : ' · indisponibil pentru TTS'}`, resource.remote_id);
      option.disabled = !usable;
      select.add(option);
    }
    select.value = resources.some(resource => resource.remote_id === selected) ? selected : '';
    wrap.append(select);
    if (!resources.length) wrap.append(node('small', 'API-ul nu a returnat opțiuni. Actualizează catalogul sau verifică permisiunile cheii.', 'helper'));
    if (selected && !resources.some(resource => resource.remote_id === selected && resource.available)) {
      wrap.append(node('small', 'Selecția salvată nu mai este disponibilă; alege o altă opțiune.', 'settings-limitation'));
    }
    fields.append(wrap);
    return select;
  };
  const model = picker('Model implicit', catalog?.models || [], production.model_id, true);
  const voice = picker('Voce implicită', catalog?.voices || [], production.voice_id, false);
  const overrideWrap = node('label', '', 'settings-toggle');
  const override = document.createElement('input');
  override.type = 'checkbox';
  override.checked = production.allow_production_override !== false;
  override.setAttribute('aria-label', 'Permite suprascrierea de către producție');
  overrideWrap.append(override, document.createTextNode(' Permite suprascrierea de către producție (canal, serial, episod, scenă)'));
  fields.append(overrideWrap);
  const save = node('button', 'Salvează valorile implicite', 'secondary');
  save.addEventListener('click', () => run(() => api(
    `/settings/integrations/${connection.id}/production`,
    { method: 'PUT', body: JSON.stringify({ model_id: model.value || null, voice_id: voice.value || null,
      allow_production_override: override.checked, expected_version: production.version }) },
  ), 'Valori implicite salvate.'));
  section.append(fields, save, node('p', 'Alege apoi această conexiune pentru Voce / TTS în serviciile de producție. Autentificarea rămâne verificată independent de selecții.', 'helper'));
  host.append(section);
}
