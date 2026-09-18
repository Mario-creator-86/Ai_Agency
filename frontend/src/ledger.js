/**
 * The live ledger: everything the studio does and says, in the order it happened.
 *
 * The activity log listed event type names with an id; the Owner could see that "an agent
 * answered" but not what it said, and that "a workflow was created" but not where the work
 * stands. The ledger reads the same events and tells the story: who did it (the employee's
 * name when the event belongs to one), what it was in plain words, and the text that was
 * said or decided, taken from the event's payload. It also keeps one line at the top that
 * says where production is right now.
 *
 * Two sources feed it, both events already recorded by the backend: the live socket, for the
 * handful of event types the outbox streams, and the events endpoint, polled after each
 * snapshot for everything else. Entries are deduplicated by event id and ordered by sequence,
 * so the two sources never produce a double or a jump backwards.
 *
 * `describeEvent` and `productionStatus` are pure, so what the ledger says is testable.
 */

const FAMILY_KIND = {
  agent: 'work',
  director: 'work',
  role: 'work',
  workforce: 'work',
  workflow: 'production',
  factual: 'production',
  media: 'production',
  research: 'production',
  story: 'production',
  runbook: 'production',
  publishing: 'production',
  channel: 'production',
  economy: 'money',
  strategy: 'money',
  analytics: 'money',
  autonomy: 'owner',
  settings: 'owner',
  provider: 'owner',
  youtube: 'owner',
  character: 'owner',
  studio: 'system',
  office: 'system',
  experiment: 'system',
};

/** Kinds the filter chips offer, in display order. */
export const KINDS = [
  ['all', 'All'],
  ['speech', 'Talk'],
  ['production', 'Production'],
  ['work', 'Staff'],
  ['money', 'Money'],
  ['owner', 'Owner'],
];

/**
 * Jobs the scheduler runs on its own clock that make nothing: they read, check and tidy.
 * A restart creates several in one second, and calling them "production started" told the
 * Owner films were being made when none was (measured 2026-09-18). A job not named here -
 * the daily run above all - still reads as production.
 */
const ROUTINE_JOB = {
  WATCHDOG: 'watchdog',
  MODEL_REVIEW: 'model review',
  MODEL_RESEARCH: 'model research',
  DIRECTOR_LOOP: "the Director's loop",
  TRENDS_REFRESH: 'trends',
  WEEKLY_REVIEW: 'weekly review',
};

const STAGE_LABEL = {
  RESEARCH: 'Research',
  RESEARCHED: 'Researched',
  SCRIPTING: 'Script',
  SCRIPT_READY: 'Script ready',
  STORYBOARD: 'Storyboard',
  MEDIA_GENERATION: 'Media generation',
  RENDERING: 'Rendering',
  QUALITY_CONTROL: 'Quality control',
  READY_TO_PUBLISH: 'Ready to publish',
  PUBLISHING: 'Publishing',
  PUBLISHED: 'Published',
  ANALYTICS: 'Analytics',
  LEARNING: 'Learning',
};

/** The stages of the daily runbook, as the Owner reads them in the panel. */
const RUN_STAGE_LABEL = {
  preflight: 'preflight check',
  performance_intake: 'performance intake',
  idea_generation: 'idea generation',
  research_and_verification: 'research and verification',
  selection: 'topic selection',
  script_and_storyboard: 'script and storyboard',
  media: 'media production',
  edit_and_qc: 'edit and quality control',
  publish: 'publishing',
  post_run: 'reporting and closing the day',
  daily_log: "the day's journal",
  serial_queue: 'the serial episode',
};

/** What each kind of letter is, as the Owner would name it. */
const MAIL_INTENT = {
  REQUEST_INFO: 'question',
  REQUEST_REVIEW: 'review request',
  CHALLENGE: 'challenge',
  HANDOFF: 'guidance',
  STATUS: 'report',
  ESCALATE: 'escalation',
};

const STATUS_LABEL = {
  COMPLETED: 'completed',
  PARTIAL: 'partial',
  FAILED: 'failed',
  BLOCKED: 'blocked',
  SKIPPED: 'skipped',
  SUCCEEDED: 'succeeded',
  PASSED: 'passed',
  PUBLISHED: 'published',
  PUBLISHED_SIMULATED: 'simulated publication',
};

function stageLabel(stage) {
  return STAGE_LABEL[stage] || String(stage || '').replace(/_/g, ' ').toLowerCase();
}

function runStageLabel(stage) {
  return RUN_STAGE_LABEL[stage] || String(stage || '').replace(/_/g, ' ');
}

function statusLabel(status) {
  return STATUS_LABEL[status] || String(status || '').toLowerCase();
}

function short(text, max = 160) {
  const clean = String(text ?? '').replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

/**
 * Describe one event for the Owner.
 *
 * @param {{event_type: string, aggregate_id?: string, payload?: any}} event
 * @param {Record<string, string>} [names] agent id → display name
 * @returns {{who: string, label: string, text: string, kind: string, to?: string, thread?: string|null, forOwner?: boolean, subject?: string, excerpt?: string}}
 */
export function describeEvent(event, names = {}) {
  const type = String(event.event_type || '');
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const family = type.split('.')[0];
  const agentId = payload.agent_id || (family === 'agent' ? event.aggregate_id : null);
  const who = (agentId && names[agentId]) || payload.from_name || '';
  let label = '';
  let text = '';
  let kind = FAMILY_KIND[family] || 'system';

  switch (type) {
    case 'agent.message_sent':
      label = 'said';
      text = payload.text || payload.content || '';
      kind = 'speech';
      break;
    case 'agent.message_posted':
      label = `${payload.in_reply_to ? 'replies' : 'writes'} · ${MAIL_INTENT[payload.intent] || payload.intent || 'message'}`;
      text = [payload.subject, payload.excerpt].filter(Boolean).join(' — ');
      kind = 'speech';
      // A letter: the ledger names both ends and opens the thread it belongs to. One
      // addressed to the Owner is the Owner's business: it files under the Owner chip and
      // is drawn in red until it is answered.
      return {
        who: who || payload.from_name || 'Owner',
        label: payload.for_owner ? `${label} · TO YOU` : label,
        text,
        kind: payload.for_owner ? 'owner' : kind,
        to: payload.to_name || 'Director',
        thread: payload.thread_id || event.aggregate_id || null,
        forOwner: Boolean(payload.for_owner),
        subject: payload.subject || '',
        excerpt: payload.excerpt || '',
      };
    case 'agent.message_answered':
      label = 'replied to a message';
      text = payload.subject || '';
      kind = 'speech';
      break;
    case 'agent.message_resolved':
      label = `closed a message (${payload.resolved_by || ''})`;
      text = payload.subject || '';
      kind = 'speech';
      break;
    case 'agent.state_changed':
      // WORKING is production without a model — a voice being recorded, a shot generated. It
      // used to read "a terminat" (finished) while the work was only starting.
      label = payload.runtime_state === 'THINKING' || payload.runtime_state === 'WORKING' ? 'working' : 'finished';
      text = payload.detail || (payload.task_type ? `task ${payload.task_type}` : '');
      break;
    case 'agent.run_completed':
      label = `task ${statusLabel(payload.status)}`;
      text = [payload.task_type, payload.model_name].filter(Boolean).join(' · ');
      break;
    case 'agent.paused':
      label = 'paused';
      break;
    case 'agent.resumed':
      label = 'resumed';
      break;
    case 'agent.hired':
      label = 'hired';
      text = [payload.display_name, payload.role].filter(Boolean).join(' · ');
      break;
    case 'director.review_completed':
      label = 'the Director reviewed the day';
      text = `${payload.reviewed ?? 0} messages, ${payload.applied ?? 0} decisions`;
      break;
    case 'workflow.created':
    case 'workflow.job_scheduled':
    case 'workflow.job_activated':
      if (type === 'workflow.created' && !payload.current_stage && ROUTINE_JOB[payload.workflow_type]) {
        label = 'routine job started';
        text = ROUTINE_JOB[payload.workflow_type];
        kind = 'system';
        break;
      }
      label = type === 'workflow.created' ? 'production started' : 'workflow scheduled';
      text = payload.current_stage ? `stage: ${stageLabel(payload.current_stage)}` : '';
      break;
    case 'factual.topic_proposed':
      label = 'topic proposed';
      text = payload.title || '';
      break;
    case 'factual.topic_selected':
      label = 'topic chosen for production';
      text = payload.title || '';
      break;
    case 'factual.source_ingested':
      label = 'source read';
      text = payload.title || payload.url || '';
      break;
    case 'factual.claim_extracted':
      label = 'claim extracted';
      text = payload.claim_text || '';
      break;
    case 'factual.claim_verified':
      label = `verdict ${payload.status || ''}`.trim();
      text = payload.claim_text || payload.evidence_quote || '';
      break;
    case 'factual.script_verified_pass':
      label = 'script verified';
      text = payload.title || '';
      break;
    case 'factual.script_approved':
      label = 'script approved by the Owner';
      text = payload.title || '';
      break;
    case 'factual.script_blocked_by_gate':
      label = 'script blocked by the gate';
      text = payload.reason || '';
      break;
    case 'media.storyboard_created':
      label = 'storyboard created';
      text = payload.title || '';
      break;
    case 'media.video_rendered':
      label = 'video rendered';
      text = payload.provider_name || '';
      break;
    case 'media.render_failed':
      label = 'render failed';
      text = payload.reason || '';
      break;
    case 'media.qc_evaluated':
      label = `quality control ${statusLabel(payload.status)}`;
      text = Array.isArray(payload.failures) ? payload.failures.join('; ') : '';
      break;
    case 'publishing.started':
      label = 'upload started';
      break;
    case 'publishing.video_published_simulated':
      label = 'simulated publication (nothing on YouTube)';
      break;
    case 'publishing.reconciled_published':
      label = 'published, confirmed by YouTube';
      text = payload.remote_video_id || '';
      break;
    case 'publishing.failed':
      label = 'publication failed';
      text = payload.reason || payload.error || '';
      break;
    case 'provider.model_discovered':
      label = 'model found at the provider';
      text = payload.model_name || '';
      break;
    case 'provider.registered':
      label = 'provider registered';
      text = [payload.name, payload.provider_type].filter(Boolean).join(' · ');
      break;
    case 'agent.model_assigned':
      label = 'model assigned';
      break;
    case 'role.created':
      label = 'role created';
      text = [payload.name, payload.mission].filter(Boolean).join(' — ');
      break;
    case 'role.contract_seeded':
      label = 'work contract written';
      text = payload.name || '';
      break;
    case 'settings.service_selected':
      label = 'service chosen for a task';
      break;
    case 'settings.integration_deleted':
      label = 'integration deleted';
      text = payload.kind || '';
      break;
    case 'youtube.authorization_started':
      label = 'YouTube authorisation started';
      break;
    case 'youtube.connection_created':
      label = 'YouTube connection created';
      text = payload.name || '';
      break;
    case 'youtube.verified':
      label = 'YouTube channel verified';
      text = payload.channel_title || payload.channel_id || '';
      break;
    case 'channel.created':
      label = 'channel created';
      text = [payload.channel_name, payload.channel_type].filter(Boolean).join(' · ');
      break;
    case 'publishing.intent_created':
      label = 'publication prepared';
      text = payload.title || '';
      break;
    case 'publishing.video_published':
      label = 'video published';
      text = payload.title || payload.remote_url || '';
      break;
    case 'economy.transaction_posted':
      label = 'entry in the books';
      text = [payload.kind, payload.memo, payload.amount_vr ? `${payload.amount_vr} VR$` : '']
        .filter(Boolean)
        .join(' · ');
      break;
    case 'research.host_revoked':
      label = 'source blocked';
      text = payload.host || '';
      break;
    case 'studio.renamed':
      label = 'the studio was renamed';
      text = [payload.previous_name, payload.name].filter(Boolean).join(' → ');
      break;
    case 'trends.snapshot_recorded':
      label = 'trends read';
      text = `${payload.count ?? 0} new of ${payload.seen ?? 0} (${payload.geo || ''})${Array.isArray(payload.top) && payload.top.length ? ` · ${payload.top.slice(0, 3).join(', ')}` : ''}`;
      break;
    case 'trends.unavailable':
      label = 'trends could not be read';
      text = payload.reason || '';
      break;
    case 'media.model_research_recorded':
      label = `model research · ${payload.purpose || ''}`;
      text = `${payload.steward ? `${payload.steward}: ` : ''}${payload.annotated ?? 0} models judged from ${payload.pages ?? 0} pages${payload.recommended ? ` · recommended ${payload.recommended}` : ''}${payload.changed ? ' · set as default' : ''}`;
      kind = 'production';
      break;
    case 'provider.resource_metadata_updated':
      label = 'model card updated';
      text = payload.source || '';
      break;
    case 'media.production_configured':
      label = 'production defaults';
      text = [payload.model_id ? `model ${payload.model_id}` : '', payload.voice_id ? `voice ${payload.voice_id}` : '', payload.image_model_id ? `image ${payload.image_model_id}` : '']
        .filter(Boolean)
        .join(' · ');
      break;
    case 'media.editorial_reviewed':
      label = payload.verdict === 'APPROVE' ? 'watched and approved' : 'watched and rejected';
      text = [payload.title, payload.story, Array.isArray(payload.reasons) ? payload.reasons.join('; ') : '']
        .filter(Boolean)
        .join(' — ');
      kind = 'production';
      break;
    case 'studio.history_reset':
      label = 'history cleared';
      text = `starting from zero · ${payload.events || 0} events, ${payload.messages || 0} messages, ${payload.runs || 0} runs deleted`;
      kind = 'owner';
      break;
    case 'runbook.daily_run_started':
      label = 'the day began';
      text = `${payload.stages || ''} stages · preflight ${payload.preflight || ''}`.trim();
      break;
    case 'runbook.stage_started':
      label = 'stage started';
      text = `${runStageLabel(payload.stage)}${payload.index ? ` (${payload.index}/${payload.total})` : ''}`;
      break;
    case 'runbook.stage_finished':
      label = `stage ${statusLabel(payload.status)}`;
      text = [runStageLabel(payload.stage), payload.reason].filter(Boolean).join(' — ');
      break;
    case 'runbook.daily_run_finished':
      label = `daily run ${statusLabel(payload.status)}`;
      text = payload.preflight ? `preflight ${payload.preflight}` : '';
      break;
    case 'runbook.safe_mode_entered':
      label = 'SAFE MODE';
      text = payload.reason || '';
      break;
    case 'story.daily_log_closed':
      label = "the day's journal closed";
      break;
    case 'story.episode_drafted':
      label = 'episode written';
      text = payload.title || '';
      break;
    case 'economy.provider_cost_recorded':
      label = `cost ${payload.status === 'BILLED' ? 'billed' : 'estimated'}`;
      text = [payload.provider, payload.vr ? `${payload.vr} VR$` : ''].filter(Boolean).join(' · ');
      break;
    case 'economy.budget_set':
      label = 'budget set';
      text = `${payload.period || ''} ${payload.limit_usd || ''} USD`.trim();
      break;
    case 'economy.budget_retired':
      label = 'budget retired';
      text = payload.period || '';
      break;
    case 'economy.vr_minted':
      label = 'VR$ issued from evidence';
      text = payload.vr ? `${payload.vr} VR$` : '';
      break;
    case 'economy.owner_funding_recorded':
      label = 'funding from the Owner';
      text = payload.vr ? `${payload.vr} VR$` : '';
      break;
    case 'strategy.version_promoted':
      label = 'strategy promoted';
      text = `v${payload.new_version ?? ''}`;
      break;
    case 'autonomy.stopped':
      label = 'the Owner stopped autonomy';
      break;
    case 'autonomy.stop_cleared':
      label = 'the Owner started autonomy';
      break;
    case 'research.host_tested':
      label = `site tested: ${payload.status || ''}`.trim();
      text = payload.host || '';
      break;
    case 'research.host_authorised':
      label = 'site authorised';
      text = payload.host || '';
      break;
    case 'settings.integration_saved':
      label = 'connection saved';
      text = payload.kind || '';
      break;
    case 'settings.integration_checked':
      label = `connection checked: ${payload.status || ''}`.trim();
      break;
    case 'provider.catalog_refreshed':
      label = 'catalogue updated';
      text = [payload.models != null ? `${payload.models} models` : '', payload.voices != null ? `${payload.voices} voices` : '']
        .filter(Boolean)
        .join(', ');
      break;
    case 'youtube.connected':
      label = 'YouTube account connected';
      text = payload.channel_title || '';
      break;
    case 'channel.credentials_bound':
      label = 'channel slot bound to an account';
      break;
    case 'character.identity_locks_set':
      label = 'identity locked';
      break;
    case 'studio.created':
      label = 'the studio was created';
      break;
    case 'office.room_created':
      label = 'workspace created';
      break;
    default: {
      label = type.split('.').slice(1).join(' ').replace(/_/g, ' ') || type;
      const bits = Object.entries(payload)
        .filter(([, v]) => typeof v === 'string' || typeof v === 'number')
        .slice(0, 3)
        .map(([k, v]) => `${k}: ${v}`);
      text = bits.join(' · ');
    }
  }
  return { who, label, text: short(text), kind };
}

/**
 * Where production stands, from the newest events that say so.
 *
 * @param {Array<{event_type: string, payload?: any, sequence?: number}>} events newest first
 * @returns {{stage: string|null, run: string|null, running: string|null, text: string}}
 */
export function productionStatus(events) {
  let stage = null;
  let run = null;
  let running = null;
  for (const event of events) {
    const payload = event.payload || {};
    const type = String(event.event_type);
    // A stage that started and has not been seen finishing is where the day is right now;
    // it is newer than anything the workflow can say, so it is read first and wins.
    if (running === null && (type === 'runbook.stage_started' || type === 'runbook.stage_finished')) {
      running = type === 'runbook.stage_started' ? payload.stage || null : false;
    }
    if (!stage && type.startsWith('workflow.') && payload.current_stage) {
      stage = payload.current_stage;
    }
    if (!run && type === 'runbook.daily_run_finished') {
      run = payload.status || null;
    }
    if (stage && run && running !== null) break;
  }
  const parts = [];
  if (running) parts.push(`Now: ${runStageLabel(running)}`);
  if (stage) parts.push(`production: ${stageLabel(stage)}`);
  if (run) parts.push(`last daily run ${statusLabel(run)}`);
  if (!parts.length) return { stage, run, running: null, text: 'No production in progress.' };
  const text = parts.join(' · ');
  return { stage, run, running: running || null, text: text[0].toUpperCase() + text.slice(1) };
}

/** How many entries the ledger keeps on screen. Older ones are in the events endpoint. */
export const LEDGER_CAPACITY = 400;

export class Ledger {
  /**
   * @param {{list: HTMLElement, now: HTMLElement, filters: HTMLElement, escape: (s: string) => string,
   *          onEvents?: (events: any[]) => void, onThread?: (threadId: string) => void}} parts
   */
  constructor(parts) {
    this.list = parts.list;
    this.now = parts.now;
    this.filters = parts.filters;
    this.escape = parts.escape;
    // Called once per add() with the events that were actually new, whichever source they
    // came from — the socket, the snapshot or the events endpoint. The live agent windows
    // hang off this: they must see the same stream the ledger renders, without a second
    // subscription that could drift from it.
    this.onEvents = typeof parts.onEvents === 'function' ? parts.onEvents : null;
    // A letter in the ledger opens its thread; the page decides in which window.
    this.onThread = typeof parts.onThread === 'function' ? parts.onThread : null;
    this.list.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target.closest('[data-thread]') : null;
      if (target && this.onThread) this.onThread(target.getAttribute('data-thread'));
    });
    /** @type {Map<string, any>} */
    this.events = new Map();
    this.names = {};
    this.cursor = 0;
    this.backfilled = false;
    this.kind = 'all';
    this.timezone = undefined;
    this.renderFilters();
  }

  /** Names arrive after the first events (the office layout loads later); re-render then. */
  setNames(names) {
    const next = names || {};
    const changed = JSON.stringify(next) !== JSON.stringify(this.names);
    this.names = next;
    if (changed) this.render();
  }

  clear() {
    this.events.clear();
    this.cursor = 0;
    this.backfilled = false;
    this.render();
  }

  /** Add events from any source; duplicates are ignored, order comes from the sequence. */
  add(events) {
    const fresh = [];
    for (const event of Array.isArray(events) ? events : [events]) {
      if (!event || !event.event_id || this.events.has(event.event_id)) continue;
      this.events.set(event.event_id, event);
      fresh.push(event);
      if (Number.isFinite(event.sequence)) this.cursor = Math.max(this.cursor, event.sequence);
    }
    if (this.events.size > LEDGER_CAPACITY) {
      const sorted = this.sorted();
      for (const old of sorted.slice(LEDGER_CAPACITY)) this.events.delete(old.event_id);
    }
    if (fresh.length) {
      this.render();
      if (this.onEvents) this.onEvents(fresh);
    }
    return fresh.length > 0;
  }

  /** Newest first. */
  sorted() {
    return [...this.events.values()].sort(
      (a, b) => (b.sequence ?? 0) - (a.sequence ?? 0) || String(b.timestamp).localeCompare(String(a.timestamp)),
    );
  }

  /**
   * Pull everything recorded after the ledger's cursor. On first use, start a page back so
   * the Owner sees history, not only what happens from now on.
   */
  async sync(api, snapshotCursor) {
    if (!this.backfilled && Number.isFinite(snapshotCursor)) {
      // The snapshot's twenty events already set the cursor near the end; the first sync
      // looks a page further back so the day's history is on screen, not only its tail.
      this.cursor = Math.max(0, snapshotCursor - 200);
      this.backfilled = true;
    }
    for (let page = 0; page < 3; page += 1) {
      const data = await api(`/events?after=${this.cursor}&limit=200`);
      this.add(data.events || []);
      if (Number.isFinite(data.next_cursor)) this.cursor = Math.max(this.cursor, data.next_cursor);
      if (!data.has_more) break;
    }
  }

  renderFilters() {
    this.filters.replaceChildren();
    for (const [kind, label] of KINDS) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `ledger-chip${kind === this.kind ? ' is-active' : ''}`;
      chip.textContent = label;
      chip.addEventListener('click', () => {
        this.kind = kind;
        this.renderFilters();
        this.render();
      });
      this.filters.append(chip);
    }
  }

  render() {
    const events = this.sorted();
    this.now.textContent = productionStatus(events).text;
    // A letter the Owner has answered is no longer red: the answer's event names it.
    const answered = new Set(
      events
        .filter((e) => e.event_type === 'agent.message_answered' || e.event_type === 'agent.message_resolved')
        .map((e) => e.aggregate_id),
    );
    // How long each thread is, so a letter says whether it is the first word or the fifth.
    const threadLength = new Map();
    for (const e of events) {
      if (e.event_type !== 'agent.message_posted') continue;
      const id = (e.payload && e.payload.thread_id) || e.aggregate_id;
      threadLength.set(id, (threadLength.get(id) || 0) + 1);
    }
    const rows = [];
    for (const event of events) {
      const item = describeEvent(event, this.names);
      if (this.kind !== 'all' && item.kind !== this.kind) continue;
      const time = new Date(event.timestamp || Date.now()).toLocaleTimeString('ro-RO', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZone: this.timezone,
      });
      const mail = item.thread
        ? `${item.forOwner ? ` ledger-owner-mail${answered.has(event.aggregate_id) ? ' is-answered' : ''}` : ''} ledger-mail" data-thread="${this.escape(item.thread)}" title="Open the correspondence thread`
        : '';
      const route = item.thread
        ? `<strong>${this.escape(item.who)}</strong> <span class="ledger-arrow">→</span> <strong>${this.escape(item.to)}</strong> · ${this.escape(item.label)}`
        : `${item.who ? `<strong>${this.escape(item.who)}</strong> ` : ''}${this.escape(item.label)}`;
      const letters = item.thread ? threadLength.get(item.thread) || 1 : 0;
      const body = item.thread
        ? `<div class="ledger-subject">${this.escape(item.subject || item.text)}</div>` +
          (item.excerpt ? `<div class="ledger-text">${this.escape(item.excerpt)}</div>` : '') +
          `<div class="ledger-open">Open the thread${letters > 1 ? ` · ${letters} scrisori` : ''} ↗</div>`
        : item.text ? `<div class="ledger-text">${this.escape(item.text)}</div>` : '';
      rows.push(
        `<li class="ledger-item ledger-${item.kind}${mail}"><time>${this.escape(time)}</time><div>` +
          `<div class="ledger-head">${route}</div>` +
          body +
          `</div></li>`,
      );
      if (rows.length >= 150) break;
    }
    this.list.innerHTML = rows.length
      ? rows.join('')
      : '<li class="ledger-empty">Nothing recorded yet for this filter.</li>';
  }
}
