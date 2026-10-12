/**
 * THE DAY'S GOAL (2026-10-12, the Owner at 14:00: «Putem urmări goal-ul de generare câte 2 pe
 * fiecare canal?»). At the head of the register, under «Ce se întâmplă acum», the snapshot's
 * `goal` (backend/app/goal.py): one line for the day and, per channel, what was published today,
 * what is in work and where it stands, what is blocked and whose the wait is, and for the serial
 * the next episode. Nothing is counted here: every number, every title and every sentence is the
 * record's own, in the backend's Romanian; the page lays them out and tags each item with whose
 * it is («Directoarea», «studioul», «decizia ta»). A goal the backend could not read (`{}`) draws
 * nothing, and the block stays hidden.
 *
 * `goalTallyHtml` is pure, so what the block says is node-tested; `renderGoalTally` writes it
 * once per change (the snapshot arrives every five seconds).
 */

/** A channel with no name in the record, by its type (publishing ChannelRecord.channel_type). */
const CHANNEL_WORDS = { MAIN_FACTUAL: 'Shorturi', OFFICE_SERIAL: 'Serialul biroului' };
/** Whose an item's wait or work is (goal.py OWNER / DIRECTOR / STUDIO), as the tag says it. */
const WHOSE_WORDS = { owner: 'decizia ta', director: 'Directoarea', studio: 'studioul' };

/**
 * @typedef {{title?: string, at?: string, url?: string|null}} PublishedItem
 * @typedef {{storyboard_id?: string, title?: string, whose?: string, words_ro?: string, since?: string}} WorkItem
 * @typedef {{channel_type?: string, channel_id?: string|null, channel_name?: string|null, target?: number,
 *   published?: PublishedItem[], in_work?: WorkItem[], blocked?: WorkItem[],
 *   next_episode?: {title?: string, status?: string, words_ro?: string}|null}} GoalChannel
 * @typedef {{day?: string, target_per_channel?: number, channels?: GoalChannel[], words_ro?: string}} Goal
 * @typedef {(value: unknown) => string} Escape
 */

/** @param {unknown} url only a web address is linked; anything else is said without a link */
function webAddress(url) {
  const text = String(url ?? '').trim();
  return /^https?:\/\//i.test(text) ? text : '';
}

/** «din 2026-10-11 09:12»: when the film entered the record (goal.py `since`, YYYY-MM-DDTHH:MM). @param {unknown} since */
function sinceWords(since) {
  const text = String(since ?? '').trim();
  return text ? `din ${text.replace('T', ' ')}` : '';
}

/**
 * One item of «în lucru» or «blocat»: the film, where it stands in the record's words, and whose
 * it is.
 * @param {WorkItem} item
 * @param {Escape} e
 */
function workItemHtml(item, e) {
  const whose = String(item.whose || '').toLowerCase();
  const tag = WHOSE_WORDS[/** @type {keyof typeof WHOSE_WORDS} */ (whose)];
  const since = sinceWords(item.since);
  return (
    `<li class="goal-item"${since ? ` title="${e(since)}"` : ''}>` +
    `<span class="goal-title">«${e(item.title || '…')}»</span>` +
    (item.words_ro ? ` <span class="goal-words">${e(item.words_ro)}</span>` : '') +
    (tag ? ` <span class="goal-tag is-${e(whose)}">${e(tag)}</span>` : '') +
    `</li>`
  );
}

/**
 * A film published today: its title, linked where the record has its address.
 * @param {PublishedItem} item
 * @param {Escape} e
 */
function publishedItemHtml(item, e) {
  const url = webAddress(item.url);
  return (
    `<li class="goal-item goal-item-published"><span class="goal-title">«${e(item.title || '…')}»</span>` +
    (url ? ` <a class="goal-link" href="${e(url)}" target="_blank" rel="noopener">deschide ↗</a>` : '') +
    `</li>`
  );
}

/**
 * @param {string} label
 * @param {WorkItem[]} items
 * @param {string} bucket
 * @param {Escape} e
 */
function groupHtml(label, items, bucket, e) {
  return (
    `<div class="goal-group goal-group-${e(bucket)}"><span class="goal-group-label">${e(label)}</span>` +
    `<ul class="goal-items">${items.map((item) => workItemHtml(item, e)).join('')}</ul></div>`
  );
}

/**
 * One channel's block.
 * @param {GoalChannel} channel
 * @param {number} fallbackTarget
 * @param {Escape} e
 */
function channelHtml(channel, fallbackTarget, e) {
  const type = String(channel.channel_type || '');
  const name = String(channel.channel_name || CHANNEL_WORDS[/** @type {keyof typeof CHANNEL_WORDS} */ (type)] || type || 'Canal');
  const target = Number.isFinite(Number(channel.target)) && channel.target !== null && channel.target !== undefined ? Number(channel.target) : fallbackTarget;
  const published = Array.isArray(channel.published) ? channel.published : [];
  const inWork = Array.isArray(channel.in_work) ? channel.in_work : [];
  const blocked = Array.isArray(channel.blocked) ? channel.blocked : [];
  const next = channel.next_episode && typeof channel.next_episode === 'object' ? channel.next_episode : null;
  const done = target > 0 && published.length >= target;
  const head =
    `<h3 class="goal-channel-head"><span class="goal-channel-name">${e(name)}</span>` +
    `<span class="goal-count${done ? ' is-done' : ''}">publicate ${published.length}/${target}</span></h3>`;
  const parts = [head];
  if (published.length) parts.push(`<ul class="goal-items goal-published">${published.map((item) => publishedItemHtml(item, e)).join('')}</ul>`);
  if (inWork.length) parts.push(groupHtml('în lucru', inWork, 'in-work', e));
  if (blocked.length) parts.push(groupHtml('blocat', blocked, 'blocked', e));
  if (next) {
    parts.push(
      `<p class="goal-next"><span class="goal-group-label">episodul următor</span> ` +
        `<span class="goal-title">«${e(next.title || '…')}»</span>` +
        (next.words_ro ? ` <span class="goal-words">${e(next.words_ro)}</span>` : '') +
        `</p>`,
    );
  }
  if (!published.length && !inWork.length && !blocked.length && !next) parts.push('<p class="goal-empty">Nimic publicat azi, nimic în lucru.</p>');
  return `<section class="goal-channel" data-channel="${e(type)}">${parts.join('')}</section>`;
}

/**
 * The block's markup, or '' when the record has no goal to show.
 * @param {Goal|null|undefined} goal the snapshot's `goal`
 * @param {Escape} escape
 */
export function goalTallyHtml(goal, escape) {
  if (!goal || typeof goal !== 'object' || !Array.isArray(goal.channels) || !goal.channels.length) return '';
  const target = Number.isFinite(Number(goal.target_per_channel)) && goal.target_per_channel ? Number(goal.target_per_channel) : 2;
  const words = typeof goal.words_ro === 'string' ? goal.words_ro.trim() : '';
  const line = words ? `<p class="goal-line">${escape(words)}</p>` : '';
  const channels = goal.channels
    .filter((channel) => channel && typeof channel === 'object')
    .map((channel) => channelHtml(channel, target, escape))
    .join('');
  return `${line}<div class="goal-channels">${channels}</div>`;
}

/** What each host last showed, so a snapshot that says the same thing redraws nothing. */
const shown = new WeakMap();

/**
 * Draws the block into its host, hidden while the record has no goal.
 * @param {{hidden: boolean, innerHTML: string}|null|undefined} host
 * @param {Goal|null|undefined} goal
 * @param {Escape} escape
 * @returns {string} the markup shown
 */
export function renderGoalTally(host, goal, escape) {
  if (!host) return '';
  const html = goalTallyHtml(goal, escape);
  host.hidden = !html;
  if (shown.get(host) === html) return html;
  shown.set(host, html);
  host.innerHTML = html;
  return html;
}
