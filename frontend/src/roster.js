/**
 * THE EMPLOYEES AS PEOPLE (W30). The employees' door («SEDIUL · ANGAJAȚI») was eight rows of
 * «78 de rulări · 3% eșecuri» with a monospace chip; nothing in it said «people in a building».
 * It is now a roster: one card per employee, with a portrait cut from the scene's own figure at
 * the employee's own desk (the page's canvas sprites and plates, never a generated image), the
 * name and the role as the data gives them, the place in the building, the state now, the last
 * real task, and the runs the backend measured. Every value is the page's record; «—» where the
 * page holds none (glossary W30).
 *
 * Nothing here fetches or draws: the cards are words and numbers (rosterCards, rosterHtml), and
 * the portrait's window and pose are pure (portraitWindow, stillFrame). The drawing is the
 * renderer's (hq_world.js HQRenderer.drawPortrait).
 */
import { counted, agoWords } from './hq_readouts.js';
import { deskPlace, lifecycleWord, workWord } from './dialog_words.js';
import { animationFor } from './hq_agents.js';

/** The place of an employee with no desk in the building (glossary W30). */
export const NO_DESK = 'fără birou';

/**
 * The window of the world a portrait shows, around a seat [x, y, w, h] in world px: the head,
 * the shoulders, the monitors and the top of the desk, as the scene draws them (the figure's
 * frame is 48×60 world px, standing on the seat's point; the head is about 20 px under its top).
 * 4:3.
 * @param {{x: number, y: number}|null|undefined} seat
 * @returns {number[]|null}
 */
export function portraitWindow(seat) {
  if (!seat || !Number.isFinite(seat.x) || !Number.isFinite(seat.y)) return null;
  const w = 44;
  const h = 33;
  return [Math.round(seat.x - w / 2), Math.round(seat.y - 47), w, h];
}

/**
 * W32, A PORTRAIT OVER THE STREAM: while the Unreal building is what the visitor sees, the portrait
 * is cut from the real frame the page holds (hq_stream.js replayPicture), at the same world window.
 * The stream's frame is laid exactly over the world (game_frame.js streamTransform; replay_still.js
 * measured 1920x1008 over 1600x840, and the Unreal figures sit on the manifest's seats: each head
 * 34-36 world px above its seat, the portrait window's 12th px). The window in the frame's pixels,
 * clamped to the frame; null when nothing of it is in the frame or there is no frame.
 * @param {number[]|null|undefined} win world [x, y, w, h]
 * @param {{width: number, height: number}|null|undefined} image the frame
 * @param {{w: number, h: number}} world
 * @returns {{sx: number, sy: number, sw: number, sh: number}|null}
 */
export function streamPortraitSource(win, image, world) {
  if (!win || !image || !(image.width > 0) || !(image.height > 0) || !(world.w > 0) || !(world.h > 0)) return null;
  const kx = image.width / world.w;
  const ky = image.height / world.h;
  const round = (/** @type {number} */ v) => Math.round(v * 1000) / 1000;
  const x0 = Math.max(0, win[0] * kx);
  const y0 = Math.max(0, win[1] * ky);
  const x1 = Math.min(image.width, (win[0] + win[2]) * kx);
  const y1 = Math.min(image.height, (win[1] + win[3]) * ky);
  if (!(x1 > x0) || !(y1 > y0)) return null;
  return { sx: round(x0), sy: round(y0), sw: round(x1 - x0), sh: round(y1 - y0) };
}

/**
 * The figure's still in a portrait: the first frame of the animation the scene plays for the
 * employee's state now (typing when working, asleep when paused, the head held on an error;
 * idle with the eyes open), at the seat's facing. -1 when the atlas has none.
 * @param {any} agent the office record (runtime_state, lifecycle)
 * @param {any} entry the atlas entry (characters.json)
 * @param {string} facing
 */
export function stillFrame(agent, entry, facing) {
  const anim = animationFor(agent, false);
  const frames = entry?.animations?.[`${anim}_${facing}`] || entry?.animations?.[`sit_idle_${facing}`] || [];
  return frames.length ? Number(frames[0]) : -1;
}

/**
 * «Sarah (Director)» → name «Sarah», role «Director»: the halves exactly as the data gives them.
 * A name with no parenthesis is the whole name, and its role is not known.
 * @param {unknown} displayName
 * @returns {{name: string, role: string}}
 */
export function personName(displayName) {
  const text = String(displayName ?? '').trim();
  const m = /^(.*?)\s*\(([^()]+)\)\s*$/.exec(text);
  if (m && m[1].trim()) return { name: m[1].trim(), role: m[2].trim() };
  return { name: text || '—', role: '—' };
}

/**
 * The order of the roster: as the building stands, the top floor first, left to right on a
 * floor; people without a desk last, in the order the backend gave them.
 * @template T
 * @param {T[]} people
 * @param {(p: T) => ({level?: number, x: number}|null|undefined)} seatOf
 * @returns {T[]}
 */
export function buildingOrder(people, seatOf) {
  return people
    .map((p, i) => ({ p, i, s: seatOf(p) }))
    .sort((a, b) => {
      if (a.s && !b.s) return -1;
      if (!a.s && b.s) return 1;
      if (a.s && b.s) {
        const la = Number(a.s.level ?? 0);
        const lb = Number(b.s.level ?? 0);
        if (la !== lb) return lb - la;
        if (a.s.x !== b.s.x) return a.s.x - b.s.x;
      }
      return a.i - b.i;
    })
    .map((e) => e.p);
}

/**
 * @typedef {{id: string, name: string, role: string, roleCode: string, place: string, desk: string,
 *   hasDesk: boolean, state: string, stateKey: string, standing: string, standingKey: string,
 *   task: string, taskWhen: string, taskFailed: boolean, runs: string, failures: string,
 *   failureShare: number|null, windowDays: number|null, label: string}} RosterCard
 */

/**
 * The cards: the measured employees (/workforce/measurements), each joined with the office's
 * record of them (desk, state now) and their last task (the snapshot's last_tasks and the
 * register, the newer). An employee the office seats but the measurement does not list is still
 * a person in the building: a card, with «—» for the runs.
 * @param {{measurements?: any, office?: any[], tasks?: Record<string, {task: string, at: number, status: string|null}>, manifest?: any, now: number}} o
 * @returns {RosterCard[]}
 */
export function rosterCards(o) {
  const measured = Array.isArray(o.measurements?.agents) ? o.measurements.agents : [];
  const office = Array.isArray(o.office) ? o.office : [];
  const byId = new Map(office.map((a) => [String(a.id || a.agent_id), a]));
  const seen = new Set();
  /** @type {{m: any, a: any, id: string}[]} */
  const people = [];
  for (const m of measured) {
    const id = String(m.agent_id || m.id || '');
    if (!id || seen.has(id)) continue;
    seen.add(id);
    people.push({ m, a: byId.get(id) || null, id });
  }
  for (const a of office) {
    const id = String(a.id || a.agent_id || '');
    if (!id || seen.has(id)) continue;
    seen.add(id);
    people.push({ m: null, a, id });
  }
  const seats = (o.manifest && o.manifest.seats) || {};
  const windowDays = Number.isFinite(Number(o.measurements?.window_days)) ? Number(o.measurements.window_days) : null;
  const ordered = buildingOrder(people, (p) => (p.a && p.a.desk_id ? seats[p.a.desk_id] : null));
  return ordered.map(({ m, a, id }) => {
    const { name, role } = personName((a && a.display_name) || (m && m.display_name));
    const desk = a && a.desk_id ? String(a.desk_id) : '';
    const hasDesk = Boolean(desk && seats[desk]);
    const stateKey = a ? String(a.runtime_state || 'IDLE').toUpperCase() : '';
    const standingKey = String((a && a.lifecycle) || (m && m.lifecycle) || '').toUpperCase();
    const last = o.tasks ? o.tasks[id] : null;
    const runs = m && Number.isFinite(Number(m.runs)) ? Number(m.runs) : null;
    const rate = m && Number.isFinite(Number(m.failure_rate)) ? Number(m.failure_rate) : null;
    const failureShare = runs && runs > 0 && rate !== null ? Math.min(1, Math.max(0, rate)) : null;
    return {
      id,
      name,
      role,
      roleCode: String((a && a.role_name) || (m && m.role_name) || ''),
      place: hasDesk ? deskPlace(o.manifest, desk) : NO_DESK,
      desk,
      hasDesk,
      state: a ? workWord(stateKey) : '—',
      stateKey: stateKey || 'UNKNOWN',
      standing: standingKey ? lifecycleWord(standingKey) : '—',
      standingKey: standingKey || 'UNKNOWN',
      task: last ? last.task : '—',
      taskWhen: last ? agoWords(o.now - last.at) : '',
      taskFailed: Boolean(last && last.status && /FAIL/.test(String(last.status).toUpperCase())),
      runs: runs === null ? '—' : runs === 0 ? 'nicio rulare' : counted(runs, 'rulare', 'rulări'),
      failures: failureShare === null ? '—' : `${Math.round(failureShare * 100)}% eșecuri`,
      failureShare,
      windowDays,
      label: `${(a && a.display_name) || (m && m.display_name) || name} — ${hasDesk ? 'deschide fișa, de la birou' : 'deschide fișa'}`,
    };
  });
}

/**
 * The roster's markup. Each card is one button: it opens the employee's inspector from the desk.
 * The portrait is a canvas the page draws after (data-portrait); until then, and for good when
 * there is nothing to draw, it stays dark with «—».
 * @param {RosterCard[]} cards
 * @param {(s: unknown) => string} escape
 */
export function rosterHtml(cards, escape) {
  if (!cards.length) return '<div class="topics-loading">Niciun angajat înregistrat.</div>';
  const days = cards.find((c) => c.windowDays !== null)?.windowDays ?? null;
  const runsLabel = days === null ? 'Rulări' : `Rulări · ${counted(days, 'zi', 'zile')}`;
  return cards
    .map((c) => {
      const meter = c.failureShare === null
        ? ''
        : `<span class="person-meter" aria-hidden="true"><span class="person-meter-fail" data-fail="${(c.failureShare * 100).toFixed(1)}"></span></span>`;
      return `
      <button type="button" class="person-card" data-agent="${escape(c.id)}" data-state="${escape(c.stateKey)}" data-standing="${escape(c.standingKey)}" aria-label="${escape(c.label)}">
        <span class="person-portrait${c.hasDesk ? '' : ' is-empty'}" data-portrait="${escape(c.id)}"><canvas class="person-canvas" width="0" height="0" aria-hidden="true"></canvas><span class="person-portrait-none" aria-hidden="true">—</span><span class="person-state"><span class="person-dot" aria-hidden="true"></span><span class="person-state-word" title="${escape(c.stateKey)}">${escape(c.state)}</span></span></span>
        <span class="person-head">
          <span class="person-place">${escape(c.place)}</span>
          <span class="person-name" title="${escape(c.roleCode)}">${escape(c.name)}</span>
          <span class="person-role">${escape(c.role)}</span>
          <span class="person-standing" title="${escape(c.standingKey)}">${escape(c.standing)}</span>
        </span>
        <span class="person-row person-task">
          <span class="person-label">Ultima sarcină</span>
          <span class="person-value">${escape(c.task)}${c.taskFailed ? ' <span class="person-failed">eșuată</span>' : ''}</span>
          ${c.taskWhen ? `<span class="person-when">${escape(c.taskWhen)}</span>` : ''}
        </span>
        <span class="person-row person-runs">
          <span class="person-label">${escape(runsLabel)}</span>
          <span class="person-figures"><span class="person-value">${escape(c.runs)}</span><span class="person-fail-share">${escape(c.failures)}</span></span>
          ${meter}
        </span>
      </button>`;
    })
    .join('');
}

/**
 * The meters' widths, through the CSSOM (the studio's policy refuses inline style attributes):
 * each failure share becomes its bar's --fail.
 * @param {ParentNode} root
 */
export function applyMeters(root) {
  for (const bar of Array.from(root.querySelectorAll('.person-meter-fail[data-fail]'))) {
    const v = Number(/** @type {HTMLElement} */ (bar).dataset.fail);
    if (Number.isFinite(v)) /** @type {HTMLElement} */ (bar).style.setProperty('--fail', `${Math.min(100, Math.max(0, v))}%`);
  }
}

/**
 * What the roster shows, as one key: the cards redraw only when one of these changes (a state,
 * a standing, a task), not on every event the socket brings.
 * @param {RosterCard[]} cards
 */
export function rosterKey(cards) {
  return cards.map((c) => [c.id, c.stateKey, c.standingKey, c.task, c.taskWhen, c.runs, c.failures, c.place].join('|')).join('#');
}

/**
 * W30: who asked for an approval, as a person of the building. The backend names the requester
 * by the employee's id or by the role's code («publisher», «video_editor», «lead_researcher»,
 * «director»); the office's record names each employee's role («Publisher», «VideoEditor»,
 * «LeadResearcher»). Only an id or an exact role match is taken; anything else is left as the
 * backend wrote it (null).
 * @param {unknown} requester
 * @param {any[]} agents the office's record
 * @returns {{id: string, name: string, seated: boolean}|null}
 */
export function requesterPerson(requester, agents) {
  const raw = String(requester ?? '').trim();
  if (!raw || !Array.isArray(agents)) return null;
  const flat = (/** @type {unknown} */ v) => String(v ?? '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const byId = agents.find((a) => String(a.id || a.agent_id) === raw);
  const byRole = byId ? null : agents.filter((a) => flat(a.role_name) && flat(a.role_name) === flat(raw));
  const agent = byId || (byRole && byRole.length === 1 ? byRole[0] : null);
  if (!agent) return null;
  return { id: String(agent.id || agent.agent_id), name: String(agent.display_name || raw), seated: Boolean(agent.desk_id) };
}
