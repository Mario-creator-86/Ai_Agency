import { PIXEL_LAYOUT } from './pixel_desks.js';

const KEY = 'amn.pixel.motion';

/**
 * The Owner explicitly wants this illustrated scene animated. Its own pause preference
 * does not change the system's reduced-motion setting or the rest of the page's effects.
 * @param {HTMLButtonElement} button
 * @param {() => void} onChange
 * @param {() => Pick<Storage, 'getItem' | 'setItem'>} storage
 */
export function bindSceneMotion(button, onChange, storage = () => window.localStorage) {
  let enabled = PIXEL_LAYOUT.life.motion_enabled === true;
  try {
    const saved = storage().getItem(KEY);
    if (saved === 'on' || saved === 'off') enabled = saved === 'on';
  } catch { /* The control also works when browser storage is unavailable. */ }

  const render = () => {
    button.setAttribute('aria-pressed', String(enabled));
    button.classList.toggle('is-on', enabled);
    button.title = enabled
      ? 'Animațiile studioului sunt pornite. Apasă pentru pauză.'
      : 'Animațiile studioului sunt oprite. Apasă pentru a le porni.';
    const label = button.querySelector('.switch-state');
    if (label) label.textContent = enabled ? 'PORNITE' : 'OPRITE';
  };
  render();
  button.addEventListener('click', () => {
    enabled = !enabled;
    try { storage().setItem(KEY, enabled ? 'on' : 'off'); } catch { /* Session-only preference. */ }
    render();
    onChange();
  });
  return { enabled: () => enabled };
}
