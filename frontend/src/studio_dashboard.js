import { escapeHtml } from './html.js';
import { taskLabel } from './ledger.js';
import { icon } from './icons.js';
import { activeProjects, completionRecord, dailyBudget, dashboardDay, dayWindow, DASHBOARD_TIME_ZONE } from './dashboard_daily.js';

export const DASHBOARD = Object.freeze({ refreshMs: 30_000, audienceMs: 60_000, taskLimit: 100, previewLimit: 4 });
const count = (/** @type {number} */ n) => n.toLocaleString('ro-RO');
const number = (/** @type {unknown} */ n) => n !== null && n !== undefined && String(n).trim() !== '' && /^\d+$/.test(String(n)) ? BigInt(String(n)).toLocaleString('ro-RO') : '—';
function localDay(/** @type {number} */ at, /** @type {string} */ timeZone) {
  try { return new Intl.DateTimeFormat('en-CA', { timeZone, year:'numeric', month:'2-digit', day:'2-digit' }).format(at); }
  catch { return new Intl.DateTimeFormat('en-CA', { timeZone:'UTC', year:'numeric', month:'2-digit', day:'2-digit' }).format(at); }
}
function checkedAt(/** @type {unknown} */ iso, /** @type {string} */ timeZone) {
  const at = Date.parse(String(iso || ''));
  if (!Number.isFinite(at)) return 'Ora măsurării nu este disponibilă';
  try { return new Intl.DateTimeFormat('ro-RO', { timeZone, day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit' }).format(at); }
  catch { return new Date(at).toISOString(); }
}

/** Open film projects and task records, not fabricated scene activity. @param {any} input */
export function dashboardMetrics(input = {}) {
  const { projects, queued, completed, budget, now = Date.now(), timeZone = 'Europe/Bucharest' } = input;
  const today = localDay(now, timeZone);
  const finished = Array.isArray(completed) ? completed.filter(row => row.status === 'COMPLETED' && Number.isFinite(Date.parse(row.completed_at)) && localDay(Date.parse(row.completed_at), timeZone) === today) : null;
  const waiting = Array.isArray(queued) ? queued.filter(row => row.status === 'QUEUED') : null;
  return {
    projects: { value: Array.isArray(projects) ? count(activeProjects(projects).length) : '—', note: Array.isArray(projects) ? activeProjects(projects).length ? 'Filme deschise, încă nepublicate' : 'Niciun proiect activ' : 'Proiectele se citesc…' },
    budget: dailyBudget(budget),
    completed: { value: finished ? count(new Set(finished.map(row => row.id)).size) : '—', note: 'Astăzi · sarcini ale agenților', title: 'Rulări reușite ale agenților, după momentul finalizării în Europe/Bucharest; fără sarcini eșuate sau pornite încă.' },
    queued: { value: waiting ? `${waiting.length >= DASHBOARD.taskLimit ? '≥' : ''}${count(waiting.length)}` : '—', note: waiting?.length >= DASHBOARD.taskLimit ? 'Cel puțin 100 · vezi coada' : 'Așteaptă preluarea' },
  };
}

/** Same ready/priority ordering as the worker, bounded by the API page. @param {any[]|null} tasks @param {number} now */
export function queuePreview(tasks, now = Date.now()) {
  const due = (/** @type {any} */ t) => Date.parse(t.next_attempt_at || t.created_at || '') || 0;
  return (tasks || []).filter(t => t.status === 'QUEUED').slice().sort((a,b) =>
    Number(due(a) > now) - Number(due(b) > now) || (Number(b.priority) || 0) - (Number(a.priority) || 0) || due(a) - due(b) || String(a.id).localeCompare(String(b.id)))
    .slice(0, DASHBOARD.previewLimit);
}

/** Channel identities are matched explicitly; total subscribers never come from subscriber gains. @param {any[]|null} channels @param {any[]|null} connections @param {number} now @param {string} timeZone */
export function audienceCards(channels, connections, now = Date.now(), timeZone = 'Europe/Bucharest') {
  const slots = (channels || []).filter(c => ['MAIN_FACTUAL','OFFICE_SERIAL'].includes(c.channel_type));
  const rows = slots.length ? slots : [{id:'factual',channel_name:'Canal factual'},{id:'serial',channel_name:'Serialul studioului'}];
  return rows.map(slot => {
    const connection = slot.remote_channel_id ? (connections || []).find(c => c.channel?.id === slot.remote_channel_id && (!slot.youtube_connection_id || c.id === slot.youtube_connection_id)) : null;
    const at = Date.parse(connection?.last_checked_at || '');
    const stale = !connection?.connected || Boolean(connection?.last_error) || !Number.isFinite(at) || now - at > DASHBOARD.audienceMs * 2;
    return { id:String(slot.id), name:connection?.channel?.title || slot.channel_name || 'Canal YouTube',
      views:number(connection?.channel?.view_count),
      subscribers:connection?.channel?.hidden_subscriber_count ? 'Ascunși' : number(connection?.channel?.subscriber_count),
      stale, note:connection ? `${stale ? 'Ultimele date' : 'YouTube'} · ${checkedAt(connection.last_checked_at,timeZone)}` : 'Conectează canalul în Setări',
    };
  });
}

/** @param {ReturnType<typeof audienceCards>} rows */
export function audienceHtml(rows) {
  return `<button class="dashboard-card dashboard-youtube" type="button" data-dashboard-open="open-publishing-btn" aria-label="YouTube · statisticile canalelor">
    <span class="dashboard-metric-icon">${icon('youtube')}</span><span class="dashboard-card-label">YouTube</span>
    <span class="dashboard-youtube-table"><span class="dashboard-youtube-head"><span>Canal</span><span>Vizualizări</span><span>Abonați</span></span>
    ${rows.map(row => `<span class="dashboard-channel-row" data-channel="${escapeHtml(row.id)}" data-stale="${row.stale}"><span class="dashboard-channel-name" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</span><strong>${escapeHtml(row.views)}</strong><strong>${escapeHtml(row.subscribers)}</strong><span class="dashboard-channel-note" title="${escapeHtml(row.note)}">${escapeHtml(row.note)}</span></span>`).join('')}</span></button>`;
}

/** A confirmed empty list, with no claim about work still running. @param {string} name @param {string} title @param {string} description */
export function dashboardEmpty(name, title, description) {
  return `<div class="dashboard-empty"><span class="dashboard-empty-icon">${icon(name)}</span><div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(description)}</p></div></div>`;
}

/** Frontend projection over existing endpoints. The sole POST re-reads authorised YouTube statistics. */
export class StudioDashboard {
  /** @param {{api:(path:string,options?:any)=>Promise<any>, root?:Document}} options */
  constructor({api, root = document}) {
    this.api = api; this.root = root; this.running = false; this.generation = 0; this.timer = 0; this.busy = false;
    /** @type {any} */ this.data = { projects:null, queued:null, completed:null, channels:null, connections:null };
    this.policy = /** @type {any} */ (null); this.budget = null; this.timeZone = 'Europe/Bucharest'; this.audienceRead = 0;
    this.readError = false; this.channelError = false;
    this.day = dayWindow(); this.completionDay = ''; this.completionCursor = 0; this.dayTimer = 0;
    this.pendingCompletions = new Map(); this.metricErrors = new Set();
    this.root.addEventListener('visibilitychange', () => { if (this.running && !this.root.hidden) void this.refresh(); });
  }
  mount() {
    const metricIcons = {projects:'folder',budget:'wallet',completed:'completed',queued:'queue'};
    for (const [name,glyph] of Object.entries(metricIcons)) {
      const card = this.root.getElementById(`dashboard-${name}-value`)?.closest('button');
      if (card && !card.querySelector('.dashboard-metric-icon')) {
        card.dataset.metric = name;
        card.insertAdjacentHTML('afterbegin',`<span class="dashboard-metric-icon">${icon(glyph)}</span>`);
      }
    }
    for (const [selector,glyph] of [['#register-panel h2','activity'],['.approvals-heading h2','seal'],['#dashboard-queue-title','queue'],['#dashboard-autonomy-title','shield']]) {
      const title = this.root.querySelector(selector);
      if (title && !title.querySelector('.dashboard-heading-icon')) title.innerHTML = `<span class="dashboard-heading-icon">${icon(glyph)}</span><span>${escapeHtml(title.textContent || '')}</span>`;
    }
    const queueKey = this.root.querySelector('.dashboard-queue-actions [data-dashboard-open]');
    if (queueKey && !queueKey.querySelector('svg')) queueKey.insertAdjacentHTML('beforeend',icon('arrow'));
    const refreshKey = this.root.getElementById('dashboard-refresh');
    if (refreshKey) refreshKey.innerHTML = icon('refresh');
    const configure = this.root.querySelector('.dashboard-autonomy button');
    if (configure && !configure.querySelector('svg')) configure.insertAdjacentHTML('afterbegin',icon('settings'));
    this.root.getElementById('dashboard-nav')?.addEventListener('click', event => {
      const key = event.target instanceof Element ? event.target.closest('button') : null;
      if (!key || key.id === 'dashboard-home') return;
      this.root.querySelectorAll('#dashboard-nav button').forEach(b => b.removeAttribute('aria-current'));
      key.setAttribute('aria-current','page');
    });
    this.root.getElementById('dashboard-home')?.addEventListener('click', () => {
      this.root.querySelectorAll('#dashboard-nav button').forEach(b => b.removeAttribute('aria-current'));
      this.root.getElementById('dashboard-home')?.setAttribute('aria-current','page');
      this.root.getElementById('office-canvas')?.focus({preventScroll:true});
    });
    this.root.addEventListener('click', event => {
      const button = event.target instanceof Element ? event.target.closest('[data-dashboard-open]') : null;
      if (button instanceof HTMLElement) this.root.getElementById(button.dataset.dashboardOpen || '')?.click();
    });
    this.root.getElementById('dashboard-refresh')?.addEventListener('click', () => { void this.refresh(); });
    // Settings keeps its original listener and dialog, in the new navigation position.
    const settings = this.root.getElementById('open-settings'), nav = this.root.getElementById('dashboard-nav-settings');
    if (settings && nav) { settings.className = 'dashboard-nav-settings'; settings.innerHTML = `${icon('settings')}<span>Setări</span>`; nav.append(settings); }
    this.paint();
  }
  /** @param {{budget?:any,policy?:any,timeZone?:string}} input */
  update(input) {
    this.checkDay();
    const measured = Date.parse(input.budget?.measured_at || '');
    const currentBudget = !Number.isFinite(measured) || dashboardDay(measured) === this.day.day;
    if (input.budget !== undefined && currentBudget && (!this.budget || !input.budget || measured >= Date.parse(this.budget.measured_at || '') || !this.budget.measured_at)) this.budget = input.budget;
    if (input.policy !== undefined) this.policy = input.policy;
    this.timeZone = DASHBOARD_TIME_ZONE;
    this.paint();
    if (!this.running && this.policy) { this.running = true; this.scheduleDay(); void this.refresh(); }
  }
  stop() {
    this.running = false; this.generation++; this.busy = false; window.clearTimeout(this.timer); window.clearTimeout(this.dayTimer);
    this.completionDay = ''; this.completionCursor = 0; this.pendingCompletions.clear();
    this.data = {projects:null,queued:null,completed:null,channels:null,connections:null}; this.budget = null; this.policy = null;
    this.audienceRead = 0; this.readError = false; this.channelError = false;
    this.day = dayWindow(); this.completionDay = ''; this.completionCursor = 0; this.dayTimer = 0;
    this.pendingCompletions = new Map(); this.metricErrors = new Set(); this.paint();
    this.root.getElementById('dashboard-refresh')?.removeAttribute('aria-busy');
  }
  async refresh() {
    if (!this.running || this.busy || this.root.hidden) return;
    this.checkDay();
    this.busy = true;
    const day = this.day.day;
    const generation = this.generation, current = () => this.running && generation === this.generation && day === dashboardDay(Date.now());
    const refreshButton = this.root.getElementById('dashboard-refresh');
    refreshButton?.setAttribute('aria-busy','true');
    try {
      const results = await Promise.allSettled([this.readProjects(current), this.api(`/tasks/queue?status=QUEUED&limit=${DASHBOARD.taskLimit}`), this.readCompleted(current), this.api('/economy/budget')]);
      if (!current()) return;
      this.readError = results.some(r=>r.status === 'rejected');
      ['projects','queued'].forEach((key,i) => {
        const result = results[i];
        if (result.status === 'fulfilled' && Array.isArray(result.value)) { this.data[key] = result.value; this.metricErrors.delete(key); }
        else { this.readError = true; this.metricErrors.add(key); }
      });
      const done = results[2], budget = results[3];
      if (done.status === 'fulfilled' && done.value) {
        this.completionDay = day; this.completionCursor = done.value.cursor;
        const records = new Map(done.value.records.map(row => [row.id, row]));
        for (const [id, row] of this.pendingCompletions) records.set(id, row);
        this.data.completed = [...records.values()]; this.pendingCompletions.clear(); this.metricErrors.delete('completed');
      } else this.metricErrors.add('completed');
      if (budget.status === 'fulfilled' && budget.value?.today) { this.budget = budget.value; this.metricErrors.delete('budget'); }
      else this.metricErrors.add('budget');
      this.paint();
      if (Date.now() - this.audienceRead >= DASHBOARD.audienceMs) {
        this.audienceRead = Date.now();
        const result = await Promise.allSettled([this.api('/publishing/channels'),this.api('/youtube/connections')]);
        if (!current()) return;
        this.channelError = result.some(r=>r.status === 'rejected');
        if (result[0].status === 'fulfilled' && Array.isArray(result[0].value?.channels)) this.data.channels = result[0].value.channels;
        if (result[1].status === 'fulfilled' && Array.isArray(result[1].value?.connections)) {
          this.data.connections = result[1].value.connections;
          this.paint();
          const slots = this.data.channels || [];
          const connections = this.data.connections.filter((/** @type {any} */ c)=>c.connected && slots.some((/** @type {any} */ slot)=>slot.remote_channel_id === c.channel?.id && (!slot.youtube_connection_id || slot.youtube_connection_id === c.id)) && (!Number.isFinite(Date.parse(c.last_checked_at)) || Date.now() - Date.parse(c.last_checked_at) >= DASHBOARD.audienceMs));
          const verified = await Promise.allSettled(connections.map((/** @type {any} */ c)=>this.api(`/youtube/connections/${encodeURIComponent(c.id)}/verify`,{method:'POST'})));
          if (!current()) return;
          verified.forEach((r,i)=>{
            const original = connections[i];
            if (r.status === 'fulfilled' && r.value?.id === original.id && r.value?.channel?.id === original.channel?.id) {
              const index = this.data.connections.findIndex((/** @type {any} */ c)=>c.id === original.id);
              this.data.connections[index] = r.value;
            } else { this.channelError = true; original.last_error = 'Actualizarea YouTube a eșuat'; }
          });
        }
      }
    } catch { if (current()) this.readError = true; }
    finally {
      if (this.running && generation === this.generation) {
        this.busy = false; refreshButton?.removeAttribute('aria-busy'); this.checkDay(); this.paint();
        window.clearTimeout(this.timer); this.timer = window.setTimeout(()=>{ void this.refresh(); },DASHBOARD.refreshMs);
      }
    }
  }
  checkDay() {
    if (this.day.day === dashboardDay(Date.now())) return;
    this.day = dayWindow(); this.data.completed = null; this.budget = null;
    this.completionDay = ''; this.completionCursor = 0; this.pendingCompletions.clear();
    this.scheduleDay(); this.paint();
  }
  scheduleDay() {
    window.clearTimeout(this.dayTimer);
    if (this.running) this.dayTimer = window.setTimeout(() => { this.checkDay(); void this.refresh(); }, Math.max(1, this.day.next - Date.now() + 20));
  }
  /** Every page belongs to one day; no 100-row queue cap and no historical totals. @param {()=>boolean} current */
  async readCompleted(current) {
    const day = this.day;
    let cursor = this.completionDay === day.day ? this.completionCursor : 0;
    const rows = new Map((this.completionDay === day.day ? this.data.completed || [] : []).map(row => [row.id, row]));
    while (current()) {
      const page = await this.api(`/events?since=${encodeURIComponent(day.since)}&after=${cursor}&limit=300`);
      if (!Array.isArray(page?.events) || !Number.isSafeInteger(page.next_cursor) || page.next_cursor < cursor || Date.parse(page.since || '') !== day.start) throw new Error('Completion page unavailable');
      for (const event of page.events) { const row = completionRecord(event, day); if (row) rows.set(row.id, row); }
      if (!page.has_more) return {records: [...rows.values()], cursor: page.next_cursor};
      if (page.next_cursor <= cursor) throw new Error('Completion cursor did not advance');
      cursor = page.next_cursor;
    }
    return null;
  }
  /** @param {any} event @param {boolean} live */
  onEvent(event, live) {
    if (!this.running || !live) return;
    this.checkDay();
    const row = completionRecord(event, this.day);
    if (row) {
      if (Array.isArray(this.data.completed)) {
        const rows = new Map(this.data.completed.map(item => [item.id, item])); rows.set(row.id, row); this.data.completed = [...rows.values()];
      } else this.pendingCompletions.set(row.id, row);
      this.paint();
    }
    if (/^(economy\.|media\.|publishing\.)/.test(event.event_type || '')) void this.refresh();
  }
  /** Read the summary pages, including older open films; no per-film detail requests. @param {()=>boolean} current */
  async readProjects(current) {
    const rows = new Map();
    let offset = 0;
    while (current()) {
      const page = await this.api(`/media/storyboards?limit=100&offset=${offset}`);
      if (!Array.isArray(page?.storyboards)) throw new Error('Project list unavailable');
      page.storyboards.forEach((/** @type {any} */ row)=>rows.set(String(row.id),row));
      if (page.next_offset === null || page.next_offset === undefined) return Array.from(rows.values());
      if (!Number.isSafeInteger(page.next_offset) || page.next_offset <= offset) throw new Error('Project page unavailable');
      offset = page.next_offset;
    }
    return null;
  }
  paint() {
    const metrics = dashboardMetrics({...this.data,budget:this.budget,timeZone:this.timeZone});
    for (const [key,row] of Object.entries(metrics)) {
      const value = this.root.getElementById(`dashboard-${key}-value`), note = this.root.getElementById(`dashboard-${key}-note`);
      if (value) { value.textContent = row.value; value.title = row.title || ''; }
      if (note) note.textContent = this.metricErrors.has(key) ? row.value === '—' ? 'Date indisponibile · se reîncearcă' : 'Ultima citire · actualizare indisponibilă' : row.note;
    }
    const names = this.root.getElementById('dashboard-project-names');
    if (names) {
      const rows = activeProjects(this.data.projects);
      const shown = rows.length > 3 ? 2 : 3;
      const html = rows.slice(0, shown).map(row => `<span class="dashboard-project-name" title="${escapeHtml(String(row.title || 'Fără titlu'))}">${escapeHtml(String(row.title || 'Fără titlu'))}</span>`).join('') + (rows.length > shown ? `<span class="dashboard-project-more">+${count(rows.length - shown)} proiecte</span>` : '');
      if (names.innerHTML !== html) names.innerHTML = html;
    }
    const progress = this.root.getElementById('dashboard-budget-progress');
    if (progress instanceof HTMLProgressElement) { progress.hidden = metrics.budget.percent === null; progress.value = metrics.budget.percent || 0; }
    const audience = this.root.getElementById('dashboard-audience');
    if (audience) {
      const rows = audienceCards(this.data.channels,this.data.connections,Date.now(),this.timeZone);
      if (this.channelError) rows.forEach(row=>{row.stale=true;row.note=`Actualizare indisponibilă · ${row.note}`;});
      const html = audienceHtml(rows);
      if (audience.innerHTML !== html) {
        const focused = this.root.activeElement instanceof HTMLElement && audience.contains(this.root.activeElement);
        audience.innerHTML = html;
        if (focused) audience.querySelector('button')?.focus({preventScroll:true});
      }
    }
    const list = this.root.getElementById('dashboard-queue-list');
    if (list) {
      const tasks = queuePreview(this.data.queued);
      const rows = tasks.map(t=>`<li><span class="dashboard-queue-mark" aria-hidden="true"></span><span>${escapeHtml(taskLabel(String(t.task_type || '')))}</span><span class="dashboard-queue-state">${Date.parse(t.next_attempt_at) > Date.now() ? 'Programată' : 'În așteptare'}</span></li>`).join('');
      const html = rows || `<li class="dashboard-queue-empty">${this.data.queued ? dashboardEmpty('queue','Coada este liberă','Sarcinile noi vor apărea aici.') : this.readError ? 'Coada nu a putut fi citită.' : 'Se citește coada…'}</li>`;
      if (list.innerHTML !== html) list.innerHTML = html;
    }
    const countBox = this.root.getElementById('dashboard-queue-count'); if (countBox) countBox.textContent = metrics.queued.value;
    const queueNote = this.root.getElementById('dashboard-queue-note');
    if (queueNote) queueNote.textContent = this.readError ? 'Ultima citire · actualizare indisponibilă' : this.data.queued?.length === 0 ? '' : this.data.queued?.length >= DASHBOARD.taskLimit ? 'Selecție din ultimele 100 de sarcini' : 'Ordine după disponibilitate și prioritate';
    const activity = this.root.getElementById('dashboard-autonomy-state');
    if (activity) { activity.textContent = !this.policy ? '—' : this.policy.autonomy_stopped ? 'Oprită' : 'Pornită'; activity.dataset.on = String(Boolean(this.policy && !this.policy.autonomy_stopped)); }
  }
}
