/**
 * YouTube channel connections.
 *
 * The Owner types four things — a name, a Google client id, a client secret and the redirect URI
 * — and then presses one button. Everything about the channel itself arrives from Google and is
 * shown back as evidence of what was authorised, never as something to fill in.
 *
 * Two details worth knowing about the shape of this file:
 *
 *   The consent tab is opened *synchronously* on the click, before the request that fetches the
 *   authorisation URL resolves. A popup opened after an await has lost the user gesture and is
 *   blocked by every browser, and a blocked popup here looks exactly like a broken feature.
 *
 *   The list refreshes when the window regains focus, but only after the Owner has actually
 *   been sent to Google, and never while a form is open. Copying a client secret out of the
 *   Google console means leaving this window and coming back, and an earlier version rebuilt the
 *   section on every return — throwing away everything typed so far. Whatever is in the form is
 *   also kept in `draft`, so no redraw from any other cause can empty it either.
 *
 * No secret ever arrives here: the API returns whether a client secret and a refresh token exist,
 * never their values, so there is nothing in this module that could render one.
 */

const STATUS_LABEL = {
  CONNECTED: 'CONNECTED',
  AUTH_REQUIRED: 'Neconectat',
  ERROR: 'Eroare',
};

function node(tag, text = '', className = '') {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function field(labelText, { value = '', type = 'text', placeholder = '', hint = '' } = {}) {
  const wrap = node('label', '', 'yt-field');
  wrap.append(node('span', labelText, 'yt-field-label'));
  const input = /** @type {HTMLInputElement} */ (node('input', '', 'dialog-input'));
  input.type = type;
  input.value = value;
  if (placeholder) input.placeholder = placeholder;
  if (type === 'password') input.autocomplete = 'off';
  wrap.append(input);
  if (hint) wrap.append(node('span', hint, 'helper'));
  return { wrap, input };
}

/** Thousands separated the way a Romanian reader expects, or a dash when Google hides the count. */
function count(value) {
  if (value === undefined || value === null || value === '') return '—';
  return Number(value).toLocaleString('ro-RO');
}

function when(iso) {
  return iso ? new Date(iso).toLocaleString('ro-RO') : '—';
}

/**
 * Render the whole section into `host`.
 *
 * @param {HTMLElement} host
 * @param {{api: Function, notify: (text: string, isError?: boolean) => void}} deps
 */
export function renderYouTubeConnections(host, { api, notify }) {
  const section = node('section', '', 'yt-section');
  host.append(section);

  let adding = false;
  let editing = null;
  //: What has been typed but not yet saved, kept outside the DOM so a redraw cannot lose it.
  //: `target` is the connection being edited, or null while adding, so an unsaved draft is never
  //: shown in the wrong form.
  let draft = null;
  //: True between opening the consent tab and the next return to this window. Without it, every
  //: switch to another application would refresh the list for no reason.
  let awaitingAuthorization = false;

  const draw = async () => {
    section.replaceChildren();
    section.append(node('h3', 'YouTube · canale conectate'));
    section.append(
      node(
        'p',
        'Salvezi datele clientului Google, apoi apeși Conectează YouTube. Identitatea canalului ' +
          'o citește studioul de la Google după ce dai consimțământul; nu o scrii tu. Tokenul ' +
          'rămâne criptat pe server și nu apare niciodată aici.',
        'helper',
      ),
    );

    let connections = [];
    try {
      connections = (await api('/youtube/connections')).connections;
    } catch (err) {
      section.append(node('p', `Conexiunile nu au putut fi citite: ${err.message}`, 'text-error'));
      return;
    }

    if (!connections.length && !adding) {
      section.append(node('p', 'Nicio conexiune YouTube încă.', 'helper'));
    }

    for (const connection of connections) {
      section.append(card(connection));
    }

    if (adding || editing) {
      section.append(form(editing));
    } else {
      const add = node('button', 'Adaugă un canal', 'secondary');
      add.addEventListener('click', () => {
        adding = true;
        draw();
      });
      section.append(add);
    }
  };

  const act = async (path, options, success) => {
    try {
      const result = await api(path, options);
      notify(success(result), false);
      await draw();
      return result;
    } catch (err) {
      notify(err.message, true);
      return null;
    }
  };

  function card(connection) {
    const article = node('article', '', 'settings-card yt-card');
    const head = node('div', '', 'yt-card-head');
    head.append(node('h4', connection.name, 'yt-card-name'));
    const badge = node(
      'span',
      STATUS_LABEL[connection.status] || connection.status,
      connection.connected ? 'tag live-badge' : 'tag',
    );
    head.append(badge);
    article.append(head);

    if (connection.channel) {
      const channel = connection.channel;
      const identity = node('div', '', 'yt-channel');
      if (channel.thumbnail_url) {
        const avatar = /** @type {HTMLImageElement} */ (node('img', '', 'yt-avatar'));
        avatar.referrerPolicy = 'no-referrer';
        avatar.src = channel.thumbnail_url;
        avatar.alt = '';
        avatar.width = 44;
        avatar.height = 44;
        identity.append(avatar);
      } else {
        const fallback = node('span', '', 'yt-avatar yt-avatar-fallback');
        fallback.setAttribute('role', 'img');
        fallback.setAttribute('aria-label', 'Canal fără imagine de profil');
        identity.append(fallback);
      }
      const text = node('div');
      text.append(node('strong', channel.title || 'Canal fără nume'));
      text.append(
        node('p', `${channel.id}${channel.custom_url ? ` · ${channel.custom_url}` : ''}`, 'helper'),
      );
      text.append(
        node(
          'p',
          `${count(channel.subscriber_count)} abonați · ${count(channel.video_count)} videoclipuri · ` +
            `${count(channel.view_count)} vizualizări`,
          'helper',
        ),
      );
      identity.append(text);
      article.append(identity);
    } else {
      article.append(node('p', 'Niciun canal autorizat încă.', 'helper'));
    }

    const meta = node('dl', '', 'yt-meta');
    const pair = (term, value) => {
      meta.append(node('dt', term), node('dd', value));
    };
    pair('Client ID', connection.client_id);
    pair('Redirect URI', connection.redirect_uri);
    pair('Client Secret', connection.has_client_secret ? 'salvat, criptat' : 'lipsește');
    pair('Refresh token', connection.has_refresh_token ? 'salvat, criptat' : 'lipsește');
    if (connection.connected_at) pair('Conectat', when(connection.connected_at));
    if (connection.last_checked_at) pair('Verificat', when(connection.last_checked_at));
    article.append(meta);

    if (connection.last_error) {
      article.append(node('p', connection.last_error, 'settings-limitation'));
    }

    const actions = node('div', '', 'settings-actions');

    const connect = node(
      'button',
      connection.connected ? 'Reconectează' : 'Conectează YouTube',
      connection.connected ? 'quiet' : 'secondary',
    );
    connect.addEventListener('click', () => {
      awaitingAuthorization = true;
      // Opened now, while the click is still a user gesture; the URL arrives a moment later.
      // No 'noopener' here: with it the browser returns null instead of a handle, and this
      // whole design depends on holding the handle long enough to set its location. The
      // opener link is cut by hand below, while the blank tab is still same-origin.
      const tab = window.open('', '_blank');
      if (tab) tab.opener = null;
      const route = connection.connected ? 'reconnect' : 'authorize';
      api(`/youtube/connections/${connection.id}/${route}`, { method: 'POST' })
        .then((started) => {
          // A blocked popup is the only reason to give up this tab instead.
          if (tab) tab.location = started.authorization_url;
          else window.location.assign(started.authorization_url);
          notify(
            'Termină autorizarea în fila Google. Când te întorci, lista se reîmprospătează singură.',
            false,
          );
        })
        .catch((err) => {
          if (tab) tab.close();
          awaitingAuthorization = false;
          notify(err.message, true);
        });
    });
    actions.append(connect);

    if (connection.connected) {
      const verify = node('button', 'Verifică', 'quiet');
      verify.addEventListener('click', () =>
        act(
          `/youtube/connections/${connection.id}/verify`,
          { method: 'POST' },
          (result) => `Canal confirmat: ${result.channel.title}.`,
        ),
      );
      actions.append(verify);

      const disconnect = node('button', 'Deconectează', 'quiet');
      disconnect.addEventListener('click', () =>
        act(
          `/youtube/connections/${connection.id}/disconnect`,
          { method: 'POST' },
          () => `${connection.name}: tokenul a fost șters și revocat la Google.`,
        ),
      );
      actions.append(disconnect);
    }

    const modify = node('button', 'Editează', 'quiet');
    modify.addEventListener('click', () => {
      editing = connection;
      adding = false;
      draw();
    });
    actions.append(modify);

    // Deletion is armed by a second click: it removes the credentials as well as the token.
    const remove = node('button', 'Șterge', 'quiet');
    remove.addEventListener('click', () => {
      if (remove.dataset.armed !== 'yes') {
        remove.dataset.armed = 'yes';
        remove.textContent = 'Confirmă ștergerea';
        return;
      }
      act(
        `/youtube/connections/${connection.id}`,
        { method: 'DELETE' },
        () => `${connection.name} a fost ștearsă.`,
      );
    });
    actions.append(remove);

    article.append(actions);
    return article;
  }

  function form(existing) {
    const wrapper = node('form', '', 'settings-card yt-form');
    wrapper.append(node('h4', existing ? `Editează ${existing.name}` : 'Adaugă un canal YouTube'));
    wrapper.append(
      node(
        'p',
        'Datele vin din Google Cloud Console, ecranul „Credentials”, pentru un OAuth client de ' +
          'tip Web application. Redirect URI trebuie trecut identic și acolo.',
        'helper',
      ),
    );

    // A draft belonging to this exact form wins over the saved values: it is what the Owner
    // typed last, and it is the only copy that exists.
    const target = existing ? existing.id : null;
    const kept = draft && draft.target === target ? draft.values : null;

    const name = field('Nume conexiune', {
      value: kept ? kept.name : existing ? existing.name : '',
      placeholder: 'Cum îi spui tu acestui canal',
    });
    const clientId = field('Google OAuth Client ID', {
      value: kept ? kept.clientId : existing ? existing.client_id : '',
      placeholder: '…apps.googleusercontent.com',
    });
    const clientSecret = field('Google OAuth Client Secret', {
      type: 'password',
      value: kept ? kept.clientSecret : '',
      placeholder: existing ? 'Lasă gol ca să păstrezi secretul salvat' : '',
      hint: existing ? 'Secretul salvat nu poate fi citit înapoi; completează doar ca să-l schimbi.' : '',
    });
    // Derived from where the application is actually served, so it is never a hardcoded host.
    const redirect = field('Redirect URI', {
      value: kept
        ? kept.redirect
        : existing
          ? existing.redirect_uri
          : `${window.location.origin}/auth/youtube/callback`,
    });

    const remember = () => {
      draft = {
        target,
        values: {
          name: name.input.value,
          clientId: clientId.input.value,
          clientSecret: clientSecret.input.value,
          redirect: redirect.input.value,
        },
      };
    };
    for (const item of [name, clientId, clientSecret, redirect]) {
      item.input.addEventListener('input', remember);
      wrapper.append(item.wrap);
    }

    const actions = node('div', '', 'settings-actions');
    // 'secondary', not 'primary': .primary is the full-width submit of a login-style form and
    // would push Renunță onto its own line here.
    const save = node('button', existing ? 'Salvează modificările' : 'Salvează datele', 'secondary');
    save.type = 'submit';
    const cancel = node('button', 'Renunță', 'quiet');
    cancel.type = 'button';
    cancel.addEventListener('click', () => {
      adding = false;
      editing = null;
      draft = null;
      draw();
    });
    actions.append(save, cancel);
    wrapper.append(actions);

    wrapper.addEventListener('submit', async (event) => {
      event.preventDefault();
      const payload = {
        command_id: crypto.randomUUID(),
        name: name.input.value.trim(),
        client_id: clientId.input.value.trim(),
        redirect_uri: redirect.input.value.trim(),
      };
      if (existing) {
        // An empty secret means "leave the stored one alone" — the interface never received it.
        if (clientSecret.input.value) payload.client_secret = clientSecret.input.value;
        // Closed before the request, so the redraw that follows a success shows the cards. A
        // failure leaves the DOM untouched, so the form and everything in it are still there;
        // only the flags need putting back.
        editing = null;
        const saved = await act(
          `/youtube/connections/${existing.id}`,
          { method: 'PATCH', body: JSON.stringify(payload) },
          (result) => `${result.name} a fost actualizată.`,
        );
        if (saved) draft = null;
        else editing = existing;
        return;
      }
      payload.client_secret = clientSecret.input.value;
      if (!payload.client_secret) {
        notify('Client Secret este obligatoriu la prima salvare.', true);
        return;
      }
      adding = false;
      const saved = await act(
        '/youtube/connections',
        { method: 'POST', body: JSON.stringify(payload) },
        (result) => `${result.name} a fost salvată. Acum apasă Conectează YouTube.`,
      );
      if (saved) draft = null;
      else adding = true;
    });

    return wrapper;
  }

  // Coming back from the Google tab is exactly when the status has changed. Coming back from
  // the password manager, the Google console or anywhere else is not, and rebuilding the section
  // then would wipe an open form, so both conditions have to hold.
  const onFocus = () => {
    if (!section.isConnected || !awaitingAuthorization || adding || editing) return;
    awaitingAuthorization = false;
    draw();
  };
  window.addEventListener('focus', onFocus);

  draw();
  return () => window.removeEventListener('focus', onFocus);
}
